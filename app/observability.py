from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Observability:
    def __init__(self, path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parents[1]
        configured = Path(path or os.getenv("AIOS_OBSERVABILITY_FILE", "data/observability.json"))
        self.path = configured if configured.is_absolute() else root / configured
        self.max_events = max(100, int(os.getenv("AIOS_OBSERVABILITY_MAX_EVENTS", "10000")))

    def record(
        self,
        category: str,
        name: str,
        *,
        success: bool = True,
        duration_ms: float | None = None,
        user_id: str | None = None,
        error: str = "",
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "occurred_at": utc_now(),
            "category": str(category)[:80],
            "name": str(name)[:160],
            "success": bool(success),
            "duration_ms": round(float(duration_ms), 3) if duration_ms is not None else None,
            "user_id": user_id,
            "error": str(error)[:2000],
            "properties": properties or {},
        }
        try:
            with _LOCK:
                payload = self._load()
                payload["events"] = [*payload["events"], event][-self.max_events:]
                self._save(payload)
            event["persisted"] = True
        except OSError:
            event["persisted"] = False
        return event

    def events(self, limit: int = 1000) -> list[dict[str, Any]]:
        with _LOCK:
            return self._load()["events"][-max(1, min(int(limit), self.max_events)):]

    def dashboard(self, gateway_store: Any, usage_tracker: Any, redis_state: Any, root: Path) -> dict[str, Any]:
        events = self.events(self.max_events)
        gateway_events = gateway_store.analytics(min(self.max_events, 1000))
        usage = usage_tracker.summary()
        api = self._api_metrics(gateway_events)
        model = self._category_metrics(events, "model")
        tools = self._category_metrics(events, "tool")
        workers = self._category_metrics(events, "worker")
        errors = [event for event in reversed(events) if not event.get("success") or event.get("category") == "error"][:50]
        users = {str(event.get("user_id")) for event in gateway_events if event.get("user_id")}
        user_events = Counter(str(event.get("user_id")) for event in gateway_events if event.get("user_id"))
        health_path = root / os.getenv("AIOS_WORKER_STATE_DIR", "data/worker_state") / "health.json"
        health = self._read_json(health_path, {"status": "unknown", "components": {}})
        return {
            "generated_at": utc_now(),
            "status": "ok" if health.get("status") in {"ok", "unknown"} else "degraded",
            "tokens": {
                "requests": usage.get("requests", 0),
                "total": usage.get("total_tokens", 0),
                "by_provider": usage.get("by_provider", {}),
            },
            "cost": {"estimated_usd": usage.get("estimated_cost_usd", 0.0), "by_provider": usage.get("by_provider", {})},
            "api": api,
            "models": model,
            "tools": tools,
            "workers": workers,
            "errors": {"count": sum(1 for event in events if not event.get("success")), "recent": errors},
            "users": {
                "unique_users": len(users), "authenticated_events": sum(user_events.values()),
                "top_users": [{"user_id": key, "events": value} for key, value in user_events.most_common(20)],
            },
            "resources": resource_metrics(),
            "gpu": gpu_metrics(),
            "queues": redis_state.queue_status(),
            "health": health,
        }

    @staticmethod
    def _event_status(event: dict[str, Any]) -> int:
        if event.get("status_code") is not None:
            return int(event["status_code"])
        return 200 if event.get("success") is True else 500

    def _api_metrics(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        durations = [float(event["duration_ms"]) for event in events if isinstance(event.get("duration_ms"), (int, float))]
        success_count = sum(1 for event in events if 200 <= self._event_status(event) < 400)
        by_path: dict[str, list[float]] = defaultdict(list)
        for event in events:
            properties = event.get("properties") if isinstance(event.get("properties"), dict) else {}
            path = str(event.get("path") or properties.get("path") or "unknown")
            if isinstance(event.get("duration_ms"), (int, float)):
                by_path[path].append(float(event["duration_ms"]))
        return {
            "requests": len(events),
            "success_rate": round(success_count / len(events), 4) if events else 0.0,
            "average_latency_ms": round(sum(durations) / len(durations), 3) if durations else 0.0,
            "p95_latency_ms": percentile(durations, 95),
            "max_latency_ms": round(max(durations), 3) if durations else 0.0,
            "by_path": [
                {"path": path, "requests": len(values), "average_latency_ms": round(sum(values) / len(values), 3)}
                for path, values in sorted(by_path.items(), key=lambda item: len(item[1]), reverse=True)[:20]
            ],
        }

    @staticmethod
    def _category_metrics(events: list[dict[str, Any]], category: str) -> dict[str, Any]:
        selected = [event for event in events if event.get("category") == category]
        durations = [float(event["duration_ms"]) for event in selected if isinstance(event.get("duration_ms"), (int, float))]
        successes = sum(1 for event in selected if event.get("success"))
        names = Counter(str(event.get("name") or "unknown") for event in selected)
        return {
            "requests": len(selected),
            "successes": successes,
            "failures": len(selected) - successes,
            "success_rate": round(successes / len(selected), 4) if selected else 0.0,
            "average_duration_ms": round(sum(durations) / len(durations), 3) if durations else 0.0,
            "p95_duration_ms": percentile(durations, 95),
            "by_name": [{"name": key, "requests": value} for key, value in names.most_common(20)],
        }

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        payload = self._read_json(self.path, {"events": []})
        return {"events": payload.get("events", []) if isinstance(payload, dict) else []}

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
        except (OSError, json.JSONDecodeError):
            return default


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((percentile_value / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def resource_metrics() -> dict[str, Any]:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return {"available": False, "error": "Install project requirements to enable CPU and memory metrics."}
    process = psutil.Process()
    memory = psutil.virtual_memory()
    return {
        "available": True,
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(),
        "memory_percent": memory.percent,
        "memory_used_bytes": memory.used,
        "memory_total_bytes": memory.total,
        "process_memory_bytes": process.memory_info().rss,
        "process_cpu_percent": process.cpu_percent(interval=None),
    }


def gpu_metrics() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False, "gpus": [], "reason": "nvidia-smi not found"}
    try:
        completed = subprocess.run(
            [executable, "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if completed.returncode != 0:
            return {"available": False, "gpus": [], "reason": completed.stderr.strip()[:500]}
        gpus = []
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != 6:
                continue
            gpus.append({
                "index": int(parts[0]), "name": parts[1], "utilization_percent": float(parts[2]),
                "memory_used_mb": float(parts[3]), "memory_total_mb": float(parts[4]), "temperature_c": float(parts[5]),
            })
        return {"available": bool(gpus), "gpus": gpus}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"available": False, "gpus": [], "reason": str(exc)}


OBSERVABILITY = Observability()