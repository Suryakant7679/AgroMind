from __future__ import annotations

import json
import os
import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RedisState:
    """Redis-backed ephemeral state with a namespaced, TTL-based key layout."""

    def __init__(self, client: Any, namespace: str = "aios") -> None:
        self.client = client
        self.namespace = namespace.strip(":") or "aios"
        self.session_ttl = int(os.getenv("AIOS_REDIS_SESSION_TTL", "86400"))
        self.cache_ttl = int(os.getenv("AIOS_REDIS_CACHE_TTL", "300"))
        self.stream_ttl = int(os.getenv("AIOS_REDIS_STREAM_TTL", "3600"))
        self.queue_ttl = int(os.getenv("AIOS_REDIS_QUEUE_TTL", "86400"))
        self.memory_ttl = int(os.getenv("AIOS_REDIS_MEMORY_TTL", "7200"))

    @classmethod
    def from_url(cls, url: str, namespace: str = "aios") -> "RedisState":
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError('Redis support requires: pip install "redis>=5,<8"') from exc
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=float(os.getenv("AIOS_REDIS_CONNECT_TIMEOUT", "2")),
            socket_timeout=float(os.getenv("AIOS_REDIS_SOCKET_TIMEOUT", "2")),
            health_check_interval=30,
        )
        return cls(client, namespace)

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def set_active_session(self, session_id: str, session: dict[str, Any]) -> bool:
        return self._set_json(f"session:{session_id}", session, self.session_ttl)

    def get_active_session(self, session_id: str) -> dict[str, Any] | None:
        value = self._get_json(f"session:{session_id}")
        if value is not None:
            self._expire(f"session:{session_id}", self.session_ttl)
        return value

    def delete_active_session(self, session_id: str) -> bool:
        return self._delete(f"session:{session_id}")

    def cache_set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        return self._set_json(f"cache:{key}", value, ttl or self.cache_ttl)

    def cache_get(self, key: str) -> Any | None:
        return self._get_json(f"cache:{key}")

    def cache_delete(self, key: str) -> bool:
        return self._delete(f"cache:{key}")

    def set_temporary_memory(self, conversation_id: str, memory: dict[str, Any]) -> bool:
        value = {**memory, "cached_at": utc_now()}
        return self._set_json(f"memory:{conversation_id}", value, self.memory_ttl)

    def get_temporary_memory(self, conversation_id: str) -> dict[str, Any] | None:
        value = self._get_json(f"memory:{conversation_id}")
        if value is not None:
            self._expire(f"memory:{conversation_id}", self.memory_ttl)
        return value

    def delete_temporary_memory(self, conversation_id: str) -> bool:
        return self._delete(f"memory:{conversation_id}")

    def rate_limit(self, identifier: str, limit: int, window_seconds: int, scope: str = "api") -> dict[str, Any]:
        """Apply an atomic fixed-window limit; connection failure permits the request."""
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]
        key = self._key(f"rate:{scope}:{digest}")
        script = """
        local current = redis.call('INCR', KEYS[1])
        if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
        local ttl = redis.call('TTL', KEYS[1])
        return {current, ttl}
        """
        try:
            current, ttl = self.client.eval(script, 1, key, int(window_seconds))
            current, ttl = int(current), max(0, int(ttl))
            return {
                "allowed": current <= limit,
                "limit": limit,
                "remaining": max(0, limit - current),
                "retry_after": ttl if current > limit else 0,
                "available": True,
            }
        except Exception:
            return {"allowed": True, "limit": limit, "remaining": limit, "retry_after": 0, "available": False}

    def set_stream_state(self, conversation_id: str, state: dict[str, Any]) -> bool:
        value = {**state, "updated_at": utc_now()}
        return self._set_json(f"stream:{conversation_id}", value, self.stream_ttl)

    def get_stream_state(self, conversation_id: str) -> dict[str, Any] | None:
        return self._get_json(f"stream:{conversation_id}")

    def append_stream_text(self, conversation_id: str, chunk: str) -> bool:
        key = self._key(f"stream:{conversation_id}:text")
        try:
            pipeline = self.client.pipeline(transaction=True)
            pipeline.append(key, chunk)
            pipeline.expire(key, self.stream_ttl)
            pipeline.execute()
            return True
        except Exception:
            return False

    def get_stream_text(self, conversation_id: str) -> str:
        try:
            return self.client.get(self._key(f"stream:{conversation_id}:text")) or ""
        except Exception:
            return ""

    def clear_stream_state(self, conversation_id: str) -> bool:
        try:
            return bool(self.client.delete(
                self._key(f"stream:{conversation_id}"),
                self._key(f"stream:{conversation_id}:text"),
            ))
        except Exception:
            return False

    def enqueue(self, queue: str, payload: dict[str, Any]) -> str | None:
        job_id = str(uuid4())
        job = {"id": job_id, "status": "pending", "payload": payload, "created_at": utc_now()}
        try:
            pipeline = self.client.pipeline(transaction=True)
            pipeline.setex(self._key(f"queue:{queue}:job:{job_id}"), self.queue_ttl, json.dumps(job))
            pipeline.lpush(self._key(f"queue:{queue}:pending"), job_id)
            pipeline.execute()
            return job_id
        except Exception:
            return None

    def claim(self, queue: str, timeout: int = 0) -> dict[str, Any] | None:
        try:
            pending = self._key(f"queue:{queue}:pending")
            processing = self._key(f"queue:{queue}:processing")
            job_id = (
                self.client.brpoplpush(pending, processing, timeout=timeout)
                if timeout > 0
                else self.client.rpoplpush(pending, processing)
            )
            if not job_id:
                return None
            key = self._key(f"queue:{queue}:job:{job_id}")
            job = json.loads(self.client.get(key) or "{}")
            job.update({"status": "processing", "claimed_at": utc_now()})
            self.client.setex(key, self.queue_ttl, json.dumps(job))
            return job
        except Exception:
            return None

    def finish(self, queue: str, job_id: str, result: Any = None, error: str = "") -> bool:
        status = "failed" if error else "completed"
        key = self._key(f"queue:{queue}:job:{job_id}")
        try:
            job = json.loads(self.client.get(key) or "{}")
            if not job:
                return False
            job.update({"status": status, "finished_at": utc_now(), "result": result, "error": error})
            pipeline = self.client.pipeline(transaction=True)
            pipeline.lrem(self._key(f"queue:{queue}:processing"), 1, job_id)
            pipeline.lpush(self._key(f"queue:{queue}:{status}"), job_id)
            pipeline.ltrim(self._key(f"queue:{queue}:{status}"), 0, 999)
            pipeline.setex(key, self.queue_ttl, json.dumps(job))
            pipeline.execute()
            return True
        except Exception:
            return False

    def queue_status(self) -> dict[str, Any]:
        queues: dict[str, dict[str, int]] = {}
        try:
            for key in self.client.scan_iter(match=self._key("queue:*")):
                key = str(key)
                if self.client.type(key) != "list":
                    continue
                parts = key.split(":")
                if len(parts) < 4 or parts[-1] not in {"pending", "processing", "completed", "failed"}:
                    continue
                queue, status = parts[-2], parts[-1]
                queues.setdefault(queue, {"pending": 0, "processing": 0, "completed": 0, "failed": 0})[status] = int(self.client.llen(key))
            return {"available": True, "queues": queues, "totals": {status: sum(item[status] for item in queues.values()) for status in ("pending", "processing", "completed", "failed")}}
        except Exception as exc:
            return {"available": False, "queues": {}, "totals": {}, "error": str(exc)}
    def cleanup_expired_state(self) -> dict[str, Any]:
        """Remove orphaned queue references; Redis expires cache/job values itself."""
        removed = 0
        lists = 0
        try:
            pattern = self._key("queue:*")
            for key in self.client.scan_iter(match=pattern):
                key = str(key)
                if self.client.type(key) != "list":
                    continue
                parts = key.split(":")
                if len(parts) < 4 or parts[-1] not in {"pending", "processing", "completed", "failed"}:
                    continue
                lists += 1
                queue = parts[-2]
                for job_id in self.client.lrange(key, 0, -1):
                    if not self.client.exists(self._key(f"queue:{queue}:job:{job_id}")):
                        removed += int(self.client.lrem(key, 0, job_id) or 0)
            cache_keys = sum(1 for _ in self.client.scan_iter(match=self._key("cache:*")))
            return {"available": True, "orphaned_queue_references_removed": removed, "queue_lists_scanned": lists, "live_cache_keys": cache_keys}
        except Exception as exc:
            return {"available": False, "orphaned_queue_references_removed": removed, "queue_lists_scanned": lists, "error": str(exc)}
    def _key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    def _set_json(self, suffix: str, value: Any, ttl: int) -> bool:
        try:
            return bool(self.client.setex(self._key(suffix), ttl, json.dumps(value)))
        except Exception:
            return False

    def _get_json(self, suffix: str) -> Any | None:
        try:
            value = self.client.get(self._key(suffix))
            return json.loads(value) if value else None
        except Exception:
            return None

    def _expire(self, suffix: str, ttl: int) -> bool:
        try:
            return bool(self.client.expire(self._key(suffix), ttl))
        except Exception:
            return False

    def _delete(self, suffix: str) -> bool:
        try:
            return bool(self.client.delete(self._key(suffix)))
        except Exception:
            return False


class NullRedisState:
    """Local fallback; durable features no-op while rate limiting stays enforced."""

    def __init__(self) -> None:
        self._rate_lock = threading.Lock()
        self._rate_buckets: dict[str, int] = {}

    def ping(self) -> bool: return False
    def set_active_session(self, *args: Any, **kwargs: Any) -> bool: return False
    def get_active_session(self, *args: Any, **kwargs: Any) -> None: return None
    def cache_set(self, *args: Any, **kwargs: Any) -> bool: return False
    def cache_get(self, *args: Any, **kwargs: Any) -> None: return None
    def cache_delete(self, *args: Any, **kwargs: Any) -> bool: return False
    def set_temporary_memory(self, *args: Any, **kwargs: Any) -> bool: return False
    def get_temporary_memory(self, *args: Any, **kwargs: Any) -> None: return None
    def delete_temporary_memory(self, *args: Any, **kwargs: Any) -> bool: return False
    def rate_limit(self, identifier: str, limit: int, window_seconds: int, scope: str = "api") -> dict[str, Any]:
        limit, window_seconds = max(1, limit), max(1, window_seconds)
        now = int(time.time())
        bucket = now // window_seconds
        identity_hash = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        key = f"{scope}:{identity_hash}:{bucket}"
        with self._rate_lock:
            count = self._rate_buckets.get(key, 0) + 1
            self._rate_buckets[key] = count
            if len(self._rate_buckets) > 10_000:
                active_suffix = f":{bucket}"
                self._rate_buckets = {item: value for item, value in self._rate_buckets.items() if item.endswith(active_suffix)}
        retry_after = window_seconds - (now % window_seconds)
        return {
            "allowed": count <= limit,
            "limit": limit,
            "remaining": max(0, limit - count),
            "retry_after": retry_after,
            "available": True,
            "backend": "memory",
        }
    def set_stream_state(self, *args: Any, **kwargs: Any) -> bool: return False
    def get_stream_state(self, *args: Any, **kwargs: Any) -> None: return None
    def get_stream_text(self, *args: Any, **kwargs: Any) -> str: return ""
    def append_stream_text(self, *args: Any, **kwargs: Any) -> bool: return False
    def clear_stream_state(self, *args: Any, **kwargs: Any) -> bool: return False
    def queue_status(self) -> dict[str, Any]: return {"available": False, "queues": {}, "totals": {}}
    def cleanup_expired_state(self) -> dict[str, Any]: return {"available": False, "orphaned_queue_references_removed": 0}
    def enqueue(self, *args: Any, **kwargs: Any) -> None: return None
    def claim(self, *args: Any, **kwargs: Any) -> None: return None
    def finish(self, *args: Any, **kwargs: Any) -> bool: return False


def create_redis_state() -> RedisState | NullRedisState:
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return NullRedisState()
    try:
        state = RedisState.from_url(url, os.getenv("AIOS_REDIS_NAMESPACE", "aios"))
        return state if state.ping() else NullRedisState()
    except Exception as exc:
        # Redis improves shared state, queues, and rate limiting, but it must not
        # prevent the public web process from starting when a managed Redis URL
        # is temporarily unavailable or configured incorrectly.
        print(f"Redis unavailable; using in-memory fallback: {exc}")
        return NullRedisState()
