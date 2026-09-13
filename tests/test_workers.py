from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from app.redis_state import RedisState
from app.store import ConversationStore
from app.workers import (
    BackgroundWorker,
    CONVERSATION_SUMMARY_QUEUE,
    EMBEDDING_QUEUE,
    MEMORY_COMPRESSION_QUEUE,
    OCR_QUEUE,
    PDF_QUEUE,
    WorkerServices,
    compress_memory,
    generate_embeddings,
    process_ocr,
    process_pdf,
    summarize_conversation,
)


class FakeState:
    def __init__(self) -> None:
        self.pending: dict[str, list[dict]] = {}
        self.finished: list[tuple[str, str, object, str]] = []
        self.enqueued: list[tuple[str, dict, str]] = []
        self.memory: dict[str, dict] = {}

    def enqueue(self, queue: str, payload: dict) -> str:
        job_id = f"job-{len(self.enqueued) + 1}"
        self.enqueued.append((queue, payload, job_id))
        return job_id

    def claim(self, queue: str, timeout: int = 0):
        jobs = self.pending.get(queue, [])
        return jobs.pop(0) if jobs else None

    def finish(self, queue: str, job_id: str, result=None, error: str = "") -> bool:
        self.finished.append((queue, job_id, result, error))
        return True

    def set_temporary_memory(self, conversation_id: str, memory: dict) -> bool:
        self.memory[conversation_id] = memory
        return True


class FakeApp:
    EMBEDDING_MODEL = "test-embedding"
    EMBEDDING_DIMENSIONS = 8

    def __init__(self, artifacts: list[dict]) -> None:
        self.artifacts = artifacts
        self.upserted: list[dict] = []
        self.replaced: list[dict] = []
        self.pdf_text = ""
        self.ocr_result = ("", "unavailable", "not configured")

    def find_artifact(self, artifact_id: str):
        return next((item for item in self.artifacts if item["id"] == artifact_id), None)

    def load_artifacts(self):
        return self.artifacts

    def save_artifacts(self, artifacts):
        self.artifacts = artifacts

    def safe_artifact_path(self, path: str):
        return Path(path)

    @staticmethod
    def clean_extracted_text(text: str):
        return " ".join(text.split())

    @staticmethod
    def chunk_document_text(text: str):
        return [{"id": "chunk-0001", "index": 0, "text": text, "word_count": len(text.split())}] if text else []

    @staticmethod
    def extract_document_metadata(**kwargs):
        return {"text_length": len(kwargs["cleaned_text"]), "chunk_count": len(kwargs["chunks"]), "ocr_status": kwargs["ocr_status"]}

    def extract_pdf_text_file(self, path):
        return self.pdf_text, "no embedded text" if not self.pdf_text else ""

    @staticmethod
    def extract_pdf_text_pymupdf(path, limit=12000):
        return ""

    @staticmethod
    def extract_pdf_text_basic(content, limit=12000):
        return ""

    @staticmethod
    def usable_extracted_text(text):
        return text

    def ocr_pdf_file(self, path):
        return self.ocr_result

    def ocr_image_file(self, path):
        return self.ocr_result

    @staticmethod
    def vector_records_for_artifact(artifact):
        return [{"id": f"{artifact['id']}:chunk-0001", "embedding": [0.0] * 8}] if artifact.get("chunks") else []

    @staticmethod
    def vector_record_for_message(conversation_id, message, user_id=None):
        return {"id": f"conversation:{conversation_id}:{message['id']}", "embedding": [0.0] * 8}

    @staticmethod
    def vector_records_for_long_term_memory(memory, user_id=None):
        return [{"id": "memory:one", "embedding": [0.0] * 8}]

    def upsert_vector_records(self, records):
        self.upserted.extend(records)

    def replace_vector_source(self, source_type, records):
        self.replaced = records


class BackgroundWorkerTests(unittest.TestCase):
    def test_zero_timeout_redis_claim_is_non_blocking(self) -> None:
        client = mock.Mock()
        client.rpoplpush.return_value = None
        state = RedisState(client, "test")
        self.assertIsNone(state.claim(PDF_QUEUE, timeout=0))
        client.rpoplpush.assert_called_once_with("test:queue:pdf-processing:pending", "test:queue:pdf-processing:processing")
        client.brpoplpush.assert_not_called()

    def test_runner_finishes_successful_and_failed_jobs(self) -> None:
        state = FakeState()
        state.pending[PDF_QUEUE] = [
            {"id": "ok", "payload": {"value": 2}},
            {"id": "bad", "payload": {}},
        ]
        worker = BackgroundWorker(PDF_QUEUE, lambda payload: {"value": 4} if payload.get("value") else (_ for _ in ()).throw(ValueError("missing")), state)
        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())
        self.assertEqual(state.finished[0][2], {"value": 4})
        self.assertIn("ValueError: missing", state.finished[1][3])

    def test_pdf_worker_extracts_text_and_queues_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "document.pdf"
            path.write_bytes(b"%PDF test")
            artifact = {"id": "pdf-1", "filename": "document.pdf", "content_type": "application/pdf", "category": "pdf", "document_type": "pdf", "path": str(path), "metadata": {}}
            app, state = FakeApp([artifact]), FakeState()
            app.pdf_text = "Extracted PDF content"
            result = process_pdf({"artifact_id": "pdf-1"}, WorkerServices(state, ConversationStore(Path(temp_dir) / "chats.json"), app))
            self.assertEqual(result["text_length"], 21)
            self.assertEqual(app.artifacts[0]["ocr_status"], "not_required")
            self.assertEqual(state.enqueued[0][0], EMBEDDING_QUEUE)

    def test_pdf_without_text_hands_off_to_ocr_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scan.pdf"
            path.write_bytes(b"%PDF scan")
            artifact = {"id": "scan-1", "filename": "scan.pdf", "content_type": "application/pdf", "category": "pdf", "document_type": "pdf", "path": str(path), "metadata": {}}
            app, state = FakeApp([artifact]), FakeState()
            services = WorkerServices(state, ConversationStore(Path(temp_dir) / "chats.json"), app)
            result = process_pdf({"artifact_id": "scan-1"}, services)
            self.assertEqual(result["next_queue"], OCR_QUEUE)
            app.ocr_result = ("Recognized scanned content", "completed", "")
            ocr = process_ocr({"artifact_id": "scan-1"}, services)
            self.assertEqual(ocr["ocr_status"], "completed")
            self.assertEqual(state.enqueued[-1][0], EMBEDDING_QUEUE)

    def test_embedding_worker_indexes_artifact_and_updates_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = {"id": "doc-1", "filename": "doc.txt", "category": "file", "chunks": [{"text": "hello"}], "metadata": {}}
            app, state = FakeApp([artifact]), FakeState()
            result = generate_embeddings({"artifact_id": "doc-1"}, WorkerServices(state, ConversationStore(Path(temp_dir) / "chats.json"), app))
            self.assertEqual(result["vector_count"], 1)
            self.assertEqual(app.artifacts[0]["metadata"]["embedding_status"], "completed")
            self.assertEqual(len(app.upserted), 1)

    def test_memory_and_summary_workers_compact_and_chain_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(Path(temp_dir) / "chats.json")
            conversation = store.create_conversation()
            for index in range(10):
                store.add_message(conversation["id"], "user" if index % 2 == 0 else "assistant", f"message {index}")
            store.update_short_term_memory(
                conversation["id"],
                variables={f"v{i}": i for i in range(30)},
                tool_outputs={f"tool{i}": "x" * 400 for i in range(10)},
            )
            app, state = FakeApp([]), FakeState()
            services = WorkerServices(state, store, app)
            compressed = compress_memory({"conversation_id": conversation["id"], "recent_limit": 4, "text_limit": 200}, services)
            self.assertEqual(compressed["recent_message_count"], 4)
            self.assertEqual(compressed["variable_count"], 20)
            self.assertEqual(compressed["tool_output_count"], 6)
            self.assertEqual(state.enqueued[-1][0], CONVERSATION_SUMMARY_QUEUE)
            summary = summarize_conversation({"conversation_id": conversation["id"], "keep_recent": 3}, services)
            self.assertEqual(summary["compressed_message_count"], 7)
            self.assertIn("message 6", summary["summary"])
            self.assertEqual(state.enqueued[-1][0], EMBEDDING_QUEUE)


if __name__ == "__main__":
    unittest.main()