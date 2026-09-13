from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.store import ConversationStore
from app.worker_extras import (
    ANALYTICS_QUEUE,
    BACKUP_QUEUE,
    CACHE_CLEANUP_QUEUE,
    EMAIL_QUEUE,
    FILE_MONITOR_QUEUE,
    GIT_MONITOR_QUEUE,
    HEALTH_QUEUE,
    VECTOR_UPDATE_QUEUE,
    Scheduler,
    aggregate_analytics,
    backup_data,
    check_health,
    cleanup_cache,
    monitor_files,
    monitor_git,
    send_email,
    update_vector_index,
)
from app.workers import WorkerServices, build_workers


class ExtraFakeState:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.enqueued: list[tuple[str, dict, str]] = []

    def enqueue(self, queue: str, payload: dict) -> str:
        job_id = f"job-{len(self.enqueued) + 1}"
        self.enqueued.append((queue, payload, job_id))
        return job_id

    def ping(self) -> bool:
        return self.healthy

    def cleanup_expired_state(self) -> dict:
        return {"available": self.healthy, "orphaned_queue_references_removed": 3}


class FakeGateway:
    def analytics(self, limit: int):
        return [
            {"status_code": 200, "path": "/api/chat", "duration_ms": 10},
            {"status_code": 500, "path": "/api/chat", "duration_ms": 30},
            {"status_code": 201, "path": "/api/files", "duration_ms": 20},
        ][:limit]


class ExtraFakeApp:
    EMBEDDING_MODEL = "test"
    EMBEDDING_DIMENSIONS = 8

    def __init__(self, root: Path) -> None:
        self.ROOT = root
        self.UPLOAD_ROOT = root / "data" / "uploads"
        self.GATEWAY_STORE = FakeGateway()
        self.artifacts: list[dict] = []
        self.replaced: dict[str, list[dict]] = {}
        self.vector_error = ""

    def load_vector_records(self):
        if self.vector_error:
            raise RuntimeError(self.vector_error)
        return [{"id": "one"}]

    def load_artifacts(self):
        return self.artifacts

    @staticmethod
    def vector_records_for_artifact(artifact):
        return artifact.get("records", [])

    @staticmethod
    def vector_record_for_message(conversation_id, message, user_id=None):
        return {"id": f"conversation:{conversation_id}:{message['id']}", "source_type": "conversation"}

    @staticmethod
    def vector_records_for_long_term_memory(memory, user_id=None):
        return [{"id": f"memory:{user_id or 'local'}", "source_type": "memory"}] if memory else []

    def replace_vector_source(self, source_type, records):
        self.replaced[source_type] = records

    @staticmethod
    def chunk_document_text(text, chunk_size=1600, overlap=200):
        return [{"id": "chunk-0001", "index": 0, "text": text, "start_char": 0, "end_char": len(text)}] if text else []

    @staticmethod
    def generate_embedding(text):
        return [0.0] * 8


class RemainingWorkerTests(unittest.TestCase):
    def services(self, root: Path, state: ExtraFakeState | None = None):
        state = state or ExtraFakeState()
        store = ConversationStore(root / "data" / "conversations.json")
        app = ExtraFakeApp(root)
        return WorkerServices(state, store, app), state, store, app

    def test_all_remaining_queue_workers_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            services, state, store, app = self.services(Path(temp_dir))
            workers = build_workers(state=state, store=store, app_module=app)
            self.assertTrue({"git", "files", "cache", "analytics", "health", "email", "backup", "vector"} <= set(workers))

    def test_git_monitor_detects_changes_and_queues_vector_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            services, state, _, _ = self.services(root)
            inspector = mock.Mock()
            inspector.status.return_value = {"stdout": "clean"}
            inspector.log.return_value = {"stdout": "abc first"}
            with mock.patch("app.worker_extras.GitInspector", return_value=inspector):
                first = monitor_git({}, services)
                self.assertFalse(first["initialized"])
                inspector.status.return_value = {"stdout": " M app.py"}
                second = monitor_git({}, services)
            self.assertTrue(second["changed"])
            self.assertEqual(state.enqueued[-1][0], VECTOR_UPDATE_QUEUE)

    def test_file_monitor_detects_code_changes_after_initial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "app.py"
            source.write_text("one", encoding="utf-8")
            services, state, _, _ = self.services(root)
            first = monitor_files({}, services)
            self.assertFalse(first["initialized"])
            source.write_text("changed and longer", encoding="utf-8")
            second = monitor_files({}, services)
            self.assertIn("app.py", second["modified"])
            self.assertEqual(state.enqueued[-1][0], VECTOR_UPDATE_QUEUE)

    def test_cache_cleanup_reports_redis_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            services, _, _, _ = self.services(Path(temp_dir))
            result = cleanup_cache({}, services)
            self.assertTrue(result["available"])
            self.assertEqual(result["orphaned_queue_references_removed"], 3)

    def test_analytics_worker_writes_aggregate_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            services, _, _, _ = self.services(root)
            result = aggregate_analytics({}, services)
            self.assertEqual(result["event_count"], 3)
            self.assertEqual(result["failure_count"], 1)
            saved = json.loads((root / "data" / "worker_state" / "analytics-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["top_paths"][0]["path"], "/api/chat")

    def test_health_worker_records_degraded_state_and_alert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = ExtraFakeState(healthy=False)
            services, _, _, app = self.services(root, state)
            app.vector_error = "offline"
            with mock.patch.dict(os.environ, {"AIOS_HEALTH_ALERT_EMAIL": "admin@example.com"}):
                result = check_health({}, services)
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(state.enqueued[-1][0], EMAIL_QUEUE)

    def test_email_worker_uses_configured_smtp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            services, _, _, _ = self.services(Path(temp_dir))
            client = mock.MagicMock()
            smtp = mock.MagicMock(return_value=client)
            client.__enter__.return_value = client
            env = {
                "AIOS_SMTP_HOST": "smtp.example.com", "AIOS_SMTP_PORT": "587",
                "AIOS_SMTP_FROM": "aios@example.com", "AIOS_SMTP_STARTTLS": "false",
            }
            with mock.patch.dict(os.environ, env), mock.patch("app.worker_extras.smtplib.SMTP", smtp):
                result = send_email({"to": "user@example.com", "subject": "Ready", "body": "Done"}, services)
            self.assertTrue(result["sent"])
            client.send_message.assert_called_once()

    def test_backup_worker_archives_data_without_recursive_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data = root / "data"
            data.mkdir()
            (data / "conversations.json").write_text("{}", encoding="utf-8")
            services, _, _, _ = self.services(root)
            result = backup_data({"retention": 2}, services)
            archive_path = root / result["path"]
            self.assertTrue(archive_path.exists())
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
            self.assertIn("data/conversations.json", names)
            self.assertFalse(any(name.endswith(".zip") for name in names))

    def test_vector_update_rebuilds_all_source_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "module.py").write_text("print('hello')", encoding="utf-8")
            services, _, store, app = self.services(root)
            app.artifacts = [
                {"records": [{"id": "doc", "source_type": "document"}, {"id": "upload-code", "source_type": "code"}]}
            ]
            conversation = store.create_conversation()
            store.add_message(conversation["id"], "user", "hello")
            store.update_long_term_memory(learned_behavior=["concise"])
            result = update_vector_index({}, services)
            self.assertEqual(set(result["targets"]), {"code", "conversation", "document", "memory"})
            self.assertTrue({"code", "conversation", "document", "memory"} <= set(app.replaced))
            self.assertGreaterEqual(result["counts"]["code"], 2)

    def test_scheduler_enqueues_due_jobs_only_once_per_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            services, state, _, _ = self.services(root)
            env = {
                "AIOS_SCHEDULE_GIT_SECONDS": "10", "AIOS_SCHEDULE_FILES_SECONDS": "0",
                "AIOS_SCHEDULE_CACHE_SECONDS": "0", "AIOS_SCHEDULE_ANALYTICS_SECONDS": "0",
                "AIOS_SCHEDULE_HEALTH_SECONDS": "0", "AIOS_SCHEDULE_BACKUP_SECONDS": "0",
                "AIOS_SCHEDULE_VECTOR_SECONDS": "0",
            }
            with mock.patch.dict(os.environ, env):
                scheduler = Scheduler(services)
                first = scheduler.tick(now=100)
                second = scheduler.tick(now=105)
                third = scheduler.tick(now=111)
            self.assertEqual(first["count"], 1)
            self.assertEqual(second["count"], 0)
            self.assertEqual(third["count"], 1)
            self.assertEqual(state.enqueued[0][0], GIT_MONITOR_QUEUE)


if __name__ == "__main__":
    unittest.main()