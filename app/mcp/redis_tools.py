from __future__ import annotations

import json
import os
from typing import Any

from redis import Redis


class RedisReader:
    def __init__(self, url: str | None = None, namespace: str | None = None) -> None:
        self.client = Redis.from_url(url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True, socket_timeout=3)
        self.namespace = (namespace or os.getenv("AIOS_REDIS_NAMESPACE", "aios")).strip(":")

    def _key(self, key: str) -> str:
        prefix = f"{self.namespace}:"
        return key if key.startswith(prefix) else prefix + key

    def keys(self, pattern: str = "*", limit: int = 200) -> list[dict[str, Any]]:
        match = self._key(pattern)
        results = []
        for key in self.client.scan_iter(match=match, count=100):
            results.append({"key": key, "type": self.client.type(key), "ttl": self.client.ttl(key)})
            if len(results) >= max(1, min(limit, 1000)): break
        return results

    def get(self, key: str, max_chars: int = 50_000) -> dict[str, Any]:
        resolved = self._key(key)
        kind = self.client.type(resolved)
        if kind == "string": value = self.client.get(resolved)
        elif kind == "hash": value = self.client.hgetall(resolved)
        elif kind == "list": value = self.client.lrange(resolved, 0, 199)
        elif kind == "set": value = sorted(self.client.smembers(resolved))[:200]
        elif kind == "zset": value = self.client.zrange(resolved, 0, 199, withscores=True)
        elif kind == "none": value = None
        else: value = f"Reading Redis type '{kind}' is not supported"
        serialized = json.dumps(value, default=str)
        return {"key": resolved, "type": kind, "ttl": self.client.ttl(resolved), "value": value if len(serialized) <= max_chars else serialized[:max_chars], "truncated": len(serialized) > max_chars}

    def stats(self) -> dict[str, Any]:
        info = self.client.info("server") | self.client.info("memory")
        return {key: info.get(key) for key in ("redis_version", "uptime_in_seconds", "used_memory_human", "used_memory_peak_human")}
