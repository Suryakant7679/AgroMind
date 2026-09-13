from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


_LOCK = Lock()


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


class UsageTracker:
    def __init__(self, path: str | None = None) -> None:
        root = Path(__file__).resolve().parents[1]
        configured = path or os.getenv("AIOS_USAGE_FILE", "data/llm_usage.json")
        candidate = Path(configured)
        self.path = candidate if candidate.is_absolute() else root / candidate

    def record(
        self, provider: str, model: str, task: str, messages: list[dict[str, str]], output: str
    ) -> dict[str, Any]:
        input_tokens = estimate_tokens("\n".join(item.get("content", "") for item in messages))
        output_tokens = estimate_tokens(output)
        cost = self._cost(provider, input_tokens, output_tokens)
        entry = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "task": task,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_cost_usd": round(cost, 8),
        }
        with _LOCK:
            payload = self._load()
            payload["records"].append(entry)
            payload["records"] = payload["records"][-10000:]
            self._save(payload)
        return entry

    def summary(self) -> dict[str, Any]:
        with _LOCK:
            records = self._load()["records"]
        by_provider: dict[str, dict[str, Any]] = {}
        for item in records:
            bucket = by_provider.setdefault(
                item["provider"], {"requests": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
            )
            bucket["requests"] += 1
            bucket["total_tokens"] += item.get("total_tokens", 0)
            bucket["estimated_cost_usd"] += item.get("estimated_cost_usd", 0.0)
        for bucket in by_provider.values():
            bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"], 8)
        return {
            "requests": len(records),
            "total_tokens": sum(item.get("total_tokens", 0) for item in records),
            "estimated_cost_usd": round(sum(item.get("estimated_cost_usd", 0.0) for item in records), 8),
            "by_provider": by_provider,
        }

    def _cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        prefix = f"AIOS_{provider.upper()}"
        input_rate = float(os.getenv(f"{prefix}_INPUT_COST_PER_MILLION", "0"))
        output_rate = float(os.getenv(f"{prefix}_OUTPUT_COST_PER_MILLION", "0"))
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"records": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {"records": data.get("records", []) if isinstance(data, dict) else []}
        except (OSError, json.JSONDecodeError):
            return {"records": []}

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)
