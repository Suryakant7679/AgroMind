from __future__ import annotations

import argparse
import importlib
import os
import time
from typing import Any, Callable

from app.config import load_env
from app.redis_state import NullRedisState, create_redis_state
from app.observability import OBSERVABILITY
from app.storage import create_store
from app.worker_extras import (
    ANALYTICS_QUEUE, BACKUP_QUEUE, CACHE_CLEANUP_QUEUE, EMAIL_QUEUE,
    FILE_MONITOR_QUEUE, GIT_MONITOR_QUEUE, HEALTH_QUEUE, VECTOR_UPDATE_QUEUE,
    Scheduler, aggregate_analytics, backup_data, check_health, cleanup_cache,
    monitor_files, monitor_git, send_email, update_vector_index,
)

PDF_QUEUE = "pdf-processing"
OCR_QUEUE = "ocr"
EMBEDDING_QUEUE = "embedding-generation"
MEMORY_COMPRESSION_QUEUE = "memory-compression"
CONVERSATION_SUMMARY_QUEUE = "conversation-summary"


class WorkerServices:
    """Lazy access to application services so worker processes stay independently runnable."""

    def __init__(self, state: Any, store: Any | None = None, app_module: Any | None = None) -> None:
        self.state = state
        self.store = store or create_store()
        self._app_module = app_module

    @property
    def app(self) -> Any:
        if self._app_module is None:
            self._app_module = importlib.import_module("app.main")
        return self._app_module

    @staticmethod
    def required(payload: dict[str, Any], key: str) -> str:
        value = str(payload.get(key) or "").strip()
        if not value:
            raise ValueError(f"Worker payload requires {key}")
        return value

    def artifact(self, artifact_id: str) -> dict[str, Any]:
        artifact = self.app.find_artifact(artifact_id)
        if artifact is None:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return artifact

    def save_artifact(self, updated: dict[str, Any]) -> None:
        artifacts = self.app.load_artifacts()
        for index, artifact in enumerate(artifacts):
            if artifact.get("id") == updated.get("id"):
                artifacts[index] = updated
                self.app.save_artifacts(artifacts)
                return
        raise KeyError(f"Artifact not found: {updated.get('id')}")

    def artifact_file(self, artifact: dict[str, Any]):
        path = self.app.safe_artifact_path(str(artifact.get("path") or ""))
        if path is None or not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Artifact file is unavailable: {artifact.get('path', '')}")
        return path

    def apply_artifact_text(
        self,
        artifact: dict[str, Any],
        content: bytes,
        text: str,
        ocr_status: str,
        ocr_error: str = "",
    ) -> dict[str, Any]:
        cleaned = self.app.clean_extracted_text(text)[: int(os.getenv("AIOS_WORKER_TEXT_LIMIT", "12000"))]
        chunks = self.app.chunk_document_text(cleaned)
        metadata = self.app.extract_document_metadata(
            filename=str(artifact.get("filename") or "upload"),
            content_type=str(artifact.get("content_type") or "application/octet-stream"),
            content=content,
            category=str(artifact.get("category") or "file"),
            document_type=str(artifact.get("document_type") or artifact.get("category") or "file"),
            cleaned_text=cleaned,
            chunks=chunks,
            ocr_status=ocr_status,
        )
        updated = {
            **artifact,
            "preview": cleaned[:4000],
            "extracted_text": cleaned,
            "cleaned_text": cleaned,
            "chunks": chunks,
            "ocr_status": ocr_status,
            "ocr_error": ocr_error,
            "metadata": {
                **(artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}),
                **metadata,
                "embedding_status": "pending" if cleaned else "skipped",
            },
        }
        self.save_artifact(updated)
        return updated

    def enqueue(self, queue: str, payload: dict[str, Any]) -> str | None:
        return self.state.enqueue(queue, payload)


class BackgroundWorker:
    def __init__(self, queue: str, handler: Callable[[dict[str, Any]], dict[str, Any]], state: Any) -> None:
        self.queue = queue
        self.handler = handler
        self.state = state

    def run_once(self, timeout: int = 0) -> bool:
        job = self.state.claim(self.queue, timeout=max(0, int(timeout)))
        if not job:
            return False
        job_id = str(job.get("id") or "")
        started = time.perf_counter()
        try:
            payload = job.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("Worker job payload must be an object")
            result = self.handler(payload)
            self.state.finish(self.queue, job_id, result=result)
            OBSERVABILITY.record("worker", self.queue, duration_ms=(time.perf_counter() - started) * 1000, properties={"job_id": job_id})
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.state.finish(self.queue, job_id, error=error)
            OBSERVABILITY.record("worker", self.queue, success=False, duration_ms=(time.perf_counter() - started) * 1000, error=error, properties={"job_id": job_id})
        return True

    def run_forever(self, poll_timeout: int = 5) -> None:
        while True:
            self.run_once(timeout=poll_timeout)


def process_pdf(payload: dict[str, Any], services: WorkerServices) -> dict[str, Any]:
    artifact_id = services.required(payload, "artifact_id")
    artifact = services.artifact(artifact_id)
    if str(artifact.get("category")) != "pdf":
        raise ValueError(f"Artifact {artifact_id} is not a PDF")
    path = services.artifact_file(artifact)
    content = path.read_bytes()
    limit = int(os.getenv("AIOS_WORKER_TEXT_LIMIT", "12000"))
    text, error = services.app.extract_pdf_text_file(path)
    if not text:
        text = services.app.extract_pdf_text_pymupdf(path, limit=limit)
    if not text:
        text = services.app.usable_extracted_text(services.app.extract_pdf_text_basic(content, limit=limit))
    status = "not_required" if text else "pending"
    updated = services.apply_artifact_text(artifact, content, text, status, error if not text else "")
    next_queue = EMBEDDING_QUEUE if text else OCR_QUEUE
    next_job_id = services.enqueue(next_queue, {"artifact_id": artifact_id})
    return {
        "artifact_id": artifact_id,
        "text_length": len(updated["cleaned_text"]),
        "chunk_count": len(updated["chunks"]),
        "ocr_status": status,
        "next_queue": next_queue,
        "next_job_id": next_job_id,
    }


def process_ocr(payload: dict[str, Any], services: WorkerServices) -> dict[str, Any]:
    artifact_id = services.required(payload, "artifact_id")
    artifact = services.artifact(artifact_id)
    category = str(artifact.get("category") or "")
    if category not in {"image", "pdf"}:
        raise ValueError(f"Artifact {artifact_id} does not support OCR")
    path = services.artifact_file(artifact)
    content = path.read_bytes()
    if category == "pdf":
        text, status, error = services.app.ocr_pdf_file(path)
    else:
        text, status, error = services.app.ocr_image_file(path)
    updated = services.apply_artifact_text(artifact, content, text, status, error)
    next_job_id = services.enqueue(EMBEDDING_QUEUE, {"artifact_id": artifact_id}) if text else None
    return {
        "artifact_id": artifact_id,
        "ocr_status": status,
        "ocr_error": error,
        "text_length": len(updated["cleaned_text"]),
        "chunk_count": len(updated["chunks"]),
        "next_job_id": next_job_id,
    }


def generate_embeddings(payload: dict[str, Any], services: WorkerServices) -> dict[str, Any]:
    artifact_id = str(payload.get("artifact_id") or "").strip()
    conversation_id = str(payload.get("conversation_id") or "").strip()
    target = str(payload.get("target") or "").strip().lower()
    if artifact_id:
        artifact = services.artifact(artifact_id)
        records = services.app.vector_records_for_artifact(artifact)
        services.app.upsert_vector_records(records)
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        artifact["metadata"] = {
            **metadata,
            "embedding_model": services.app.EMBEDDING_MODEL,
            "embedding_dimensions": services.app.EMBEDDING_DIMENSIONS,
            "embedding_status": "completed",
            "vector_count": len(records),
        }
        services.save_artifact(artifact)
        return {"target": "artifact", "artifact_id": artifact_id, "vector_count": len(records)}
    if conversation_id:
        conversation = services.store.get_conversation(conversation_id)
        records = [
            services.app.vector_record_for_message(conversation_id, message, conversation.get("user_id"))
            for message in conversation.get("messages", [])
            if message.get("role") in {"user", "assistant"} and str(message.get("content") or "").strip()
        ]
        services.app.upsert_vector_records(records)
        return {"target": "conversation", "conversation_id": conversation_id, "vector_count": len(records)}
    if target == "memory":
        user_id = str(payload.get("user_id") or "").strip() or None
        memory = services.store.get_long_term_memory(user_id=user_id)
        records = services.app.vector_records_for_long_term_memory(memory, user_id)
        if user_id:
            services.app.upsert_vector_records(records)
        else:
            services.app.replace_vector_source("memory", records)
        return {"target": "memory", "user_id": user_id, "vector_count": len(records)}
    raise ValueError("Embedding worker requires artifact_id, conversation_id, or target=memory")


def compress_memory(payload: dict[str, Any], services: WorkerServices) -> dict[str, Any]:
    conversation_id = services.required(payload, "conversation_id")
    memory = services.store.compress_short_term_memory(
        conversation_id,
        recent_limit=int(payload.get("recent_limit", 6)),
        text_limit=int(payload.get("text_limit", 2000)),
    )
    services.state.set_temporary_memory(conversation_id, memory)
    next_job_id = services.enqueue(CONVERSATION_SUMMARY_QUEUE, {"conversation_id": conversation_id})
    return {
        "conversation_id": conversation_id,
        "recent_message_count": len(memory["recent_messages"]),
        "variable_count": len(memory["variables"]),
        "tool_output_count": len(memory["tool_outputs"]),
        "next_job_id": next_job_id,
    }


def summarize_conversation(payload: dict[str, Any], services: WorkerServices) -> dict[str, Any]:
    conversation_id = services.required(payload, "conversation_id")
    result = services.store.refresh_conversation_summary(
        conversation_id,
        keep_recent=int(payload.get("keep_recent", 6)),
        summary_limit=int(payload.get("summary_limit", 1600)),
    )
    result["next_job_id"] = services.enqueue(EMBEDDING_QUEUE, {"conversation_id": conversation_id})
    return result


def build_workers(state: Any | None = None, store: Any | None = None, app_module: Any | None = None) -> dict[str, BackgroundWorker]:
    state = state or create_redis_state()
    services = WorkerServices(state, store=store, app_module=app_module)
    handlers = {
        "pdf": (PDF_QUEUE, process_pdf),
        "ocr": (OCR_QUEUE, process_ocr),
        "embedding": (EMBEDDING_QUEUE, generate_embeddings),
        "memory": (MEMORY_COMPRESSION_QUEUE, compress_memory),
        "summary": (CONVERSATION_SUMMARY_QUEUE, summarize_conversation),
        "git": (GIT_MONITOR_QUEUE, monitor_git),
        "files": (FILE_MONITOR_QUEUE, monitor_files),
        "cache": (CACHE_CLEANUP_QUEUE, cleanup_cache),
        "analytics": (ANALYTICS_QUEUE, aggregate_analytics),
        "health": (HEALTH_QUEUE, check_health),
        "email": (EMAIL_QUEUE, send_email),
        "backup": (BACKUP_QUEUE, backup_data),
        "vector": (VECTOR_UPDATE_QUEUE, update_vector_index),
    }
    return {
        name: BackgroundWorker(queue, lambda payload, handler=handler: handler(payload, services), state)
        for name, (queue, handler) in handlers.items()
    }


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Run AIOS background workers")
    worker_names = ["pdf", "ocr", "embedding", "memory", "summary", "git", "files", "cache", "analytics", "health", "email", "backup", "vector"]
    parser.add_argument("--worker", choices=[*worker_names, "scheduler", "all"], default="all")
    parser.add_argument("--once", action="store_true", help="Process one job per worker, or run one scheduler tick")
    parser.add_argument("--poll-timeout", type=int, default=5)
    args = parser.parse_args()
    state = create_redis_state()
    if isinstance(state, NullRedisState):
        raise SystemExit("Background workers require a reachable REDIS_URL")
    workers = build_workers(state=state)
    if args.worker == "scheduler":
        scheduler = Scheduler(WorkerServices(state))
        if args.once:
            scheduler.tick()
            return
        try:
            while True:
                scheduler.tick()
                time.sleep(max(1, args.poll_timeout))
        except KeyboardInterrupt:
            return
    selected = list(workers.values()) if args.worker == "all" else [workers[args.worker]]
    if args.once:
        for worker in selected:
            worker.run_once(timeout=0)
        return
    try:
        while True:
            for worker in selected:
                worker.run_once(timeout=max(1, args.poll_timeout) if len(selected) == 1 else 0)
            if len(selected) > 1:
                time.sleep(max(1, args.poll_timeout))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()