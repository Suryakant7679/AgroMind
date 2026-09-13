from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.observability import Observability, gpu_metrics, percentile, resource_metrics
from app.redis_state import RedisState


class FakeGateway:
    def analytics(self, limit: int):
        return [
            {"status_code": 200, "path": "/api/chat", "duration_ms": 10, "user_id": "u1"},
            {"status_code": 500, "path": "/api/chat", "duration_ms": 30, "user_id": "u1"},
            {"success": True, "properties": {"path": "/api/files"}, "duration_ms": 20, "user_id": "u2"},
        ][:limit]


class FakeUsage:
    def summary(self):
        return {
            "requests": 2,
            "total_tokens": 300,
            "estimated_cost_usd": 0.0123,
            "by_provider": {"openai": {"requests": 2, "total_tokens": 300, "estimated_cost_usd": 0.0123}},
        }


class FakeRedis:
    def queue_status(self):
        return {"available": True, "queues": {"email": {"pending": 2}}, "totals": {"pending": 2, "processing": 0, "completed": 3, "failed": 1}}


class ObservabilityTests(unittest.TestCase):
    def test_records_and_aggregates_all_dashboard_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tracker = Observability(root / "observability.json")
            tracker.record("model", "openai/test", duration_ms=100, properties={"task": "general"})
            tracker.record("model", "openai/test", success=False, duration_ms=300, error="timeout")
            tracker.record("tool", "filesystem", duration_ms=20)
            tracker.record("tool", "terminal", success=False, duration_ms=40, error="blocked")
            tracker.record("worker", "backup", duration_ms=50)
            dashboard = tracker.dashboard(FakeGateway(), FakeUsage(), FakeRedis(), root)
            self.assertEqual(dashboard["tokens"]["total"], 300)
            self.assertEqual(dashboard["cost"]["estimated_usd"], 0.0123)
            self.assertEqual(dashboard["api"]["p95_latency_ms"], 30)
            self.assertEqual(dashboard["models"]["success_rate"], 0.5)
            self.assertEqual(dashboard["tools"]["success_rate"], 0.5)
            self.assertEqual(dashboard["users"]["unique_users"], 2)
            self.assertEqual(dashboard["queues"]["totals"]["pending"], 2)
            self.assertEqual(dashboard["errors"]["count"], 2)

    def test_percentile_and_resource_metrics(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 100], 95), 100)
        metrics = resource_metrics()
        self.assertTrue(metrics["available"])
        self.assertGreater(metrics["memory_total_bytes"], 0)
        self.assertGreaterEqual(metrics["cpu_count"], 1)

    def test_gpu_metrics_gracefully_handles_no_nvidia_runtime(self) -> None:
        with mock.patch("app.observability.shutil.which", return_value=None):
            result = gpu_metrics()
        self.assertFalse(result["available"])
        self.assertEqual(result["gpus"], [])

    def test_redis_queue_status_reports_depths(self) -> None:
        client = mock.Mock()
        keys = ["test:queue:pdf:pending", "test:queue:pdf:processing", "test:queue:email:failed"]
        client.scan_iter.return_value = keys
        client.type.return_value = "list"
        lengths = {keys[0]: 4, keys[1]: 1, keys[2]: 2}
        client.llen.side_effect = lambda key: lengths[key]
        result = RedisState(client, "test").queue_status()
        self.assertTrue(result["available"])
        self.assertEqual(result["queues"]["pdf"]["pending"], 4)
        self.assertEqual(result["totals"]["processing"], 1)
        self.assertEqual(result["totals"]["failed"], 2)

    def test_tool_and_worker_instrumentation_records_outcomes(self) -> None:
        from app.agents.specialists import SpecialistAgentRegistry
        from app.workers import BackgroundWorker

        agent = mock.Mock()
        agent.execute.return_value = {"status": "completed", "summary": "ok"}
        with mock.patch("app.agents.specialists.OBSERVABILITY.record") as tool_record:
            result = SpecialistAgentRegistry(custom=agent).execute("custom", "do it", {}, {})
        self.assertEqual(result["status"], "completed")
        tool_record.assert_called_once()
        self.assertEqual(tool_record.call_args.args[:2], ("tool", "custom"))

        state = mock.Mock()
        state.claim.return_value = {"id": "job-1", "payload": {}}
        with mock.patch("app.workers.OBSERVABILITY.record") as worker_record:
            BackgroundWorker("test", lambda payload: {"ok": True}, state).run_once()
        worker_record.assert_called_once()
        self.assertEqual(worker_record.call_args.args[:2], ("worker", "test"))


if __name__ == "__main__":
    unittest.main()