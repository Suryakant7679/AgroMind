from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import smtplib
import ssl
import zipfile
from collections import Counter
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from app.mcp.git_tools import GitInspector
from app.observability import gpu_metrics, resource_metrics

GIT_MONITOR_QUEUE = "git-monitoring"
FILE_MONITOR_QUEUE = "file-monitoring"
CACHE_CLEANUP_QUEUE = "cache-cleanup"
ANALYTICS_QUEUE = "analytics"
HEALTH_QUEUE = "health-check"
EMAIL_QUEUE = "email-notifications"
BACKUP_QUEUE = "backup"
VECTOR_UPDATE_QUEUE = "vector-index-update"

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sql", ".html", ".css", ".sh", ".yaml", ".yml"}
EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", "data", "dist", "build", "__pycache__", ".pytest_cache"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_root(services: Any) -> Path:
    return Path(getattr(services.app, "ROOT", Path(__file__).resolve().parents[1])).resolve()


def state_path(services: Any, name: str) -> Path:
    configured = Path(os.getenv("AIOS_WORKER_STATE_DIR", "data/worker_state"))
    root = project_root(services)
    directory = configured if configured.is_absolute() else root / configured
    directory = directory.resolve()
    if directory != root and root not in directory.parents:
        raise ValueError("AIOS_WORKER_STATE_DIR must stay inside the project root")
    directory.mkdir(parents=True, exist_ok=True)
    return directory / name


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def monitored_root(payload: dict[str, Any], services: Any) -> Path:
    root = project_root(services)
    requested = str(payload.get("root") or os.getenv("AIOS_MONITOR_ROOT", "")).strip()
    candidate = Path(requested).expanduser().resolve() if requested else root
    if candidate != root and root not in candidate.parents:
        raise ValueError("Monitored root must stay inside the project root")
    if not candidate.is_dir():
        raise FileNotFoundError(f"Monitored root does not exist: {candidate}")
    return candidate


def monitor_git(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    root = monitored_root(payload, services)
    inspector = GitInspector(root)
    status = inspector.status()
    head = inspector.log(limit=1)
    snapshot = {
        "root": str(root),
        "status": str(status.get("stdout") or ""),
        "head": str(head.get("stdout") or ""),
        "checked_at": utc_now(),
    }
    snapshot["digest"] = hashlib.sha256((snapshot["status"] + "\n" + snapshot["head"]).encode("utf-8")).hexdigest()
    path = state_path(services, "git-monitor.json")
    previous = read_json(path, {})
    initialized = bool(previous.get("digest"))
    changed = initialized and previous.get("digest") != snapshot["digest"]
    write_json(path, snapshot)
    next_job_id = services.enqueue(VECTOR_UPDATE_QUEUE, {"targets": ["code"]}) if changed else None
    return {**snapshot, "initialized": initialized, "changed": changed, "next_job_id": next_job_id}


def file_snapshot(root: Path) -> dict[str, dict[str, int]]:
    snapshot: dict[str, dict[str, int]] = {}
    max_files = max(100, int(os.getenv("AIOS_FILE_MONITOR_MAX_FILES", "50000")))
    for path in root.rglob("*"):
        try:
            relative = path.relative_to(root)
            if not path.is_file() or EXCLUDED_PARTS.intersection(relative.parts):
                continue
            stat = path.stat()
        except OSError:
            continue
        snapshot[relative.as_posix()] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        if len(snapshot) >= max_files:
            break
    return snapshot


def monitor_files(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    root = monitored_root(payload, services)
    current = file_snapshot(root)
    path = state_path(services, "file-monitor.json")
    previous_payload = read_json(path, {})
    previous = previous_payload.get("files", {}) if isinstance(previous_payload, dict) else {}
    initialized = bool(previous_payload.get("initialized"))
    added = sorted(set(current) - set(previous))
    deleted = sorted(set(previous) - set(current))
    modified = sorted(name for name in set(current) & set(previous) if current[name] != previous[name])
    write_json(path, {"initialized": True, "root": str(root), "checked_at": utc_now(), "files": current})
    changed_paths = [*added, *modified, *deleted]
    code_changed = any(Path(name).suffix.lower() in CODE_EXTENSIONS for name in changed_paths)
    next_job_id = services.enqueue(VECTOR_UPDATE_QUEUE, {"targets": ["code"]}) if initialized and code_changed else None
    return {
        "root": str(root), "initialized": initialized, "file_count": len(current),
        "added": added[:200], "modified": modified[:200], "deleted": deleted[:200],
        "change_count": len(changed_paths), "truncated": len(changed_paths) > 200,
        "next_job_id": next_job_id,
    }


def cleanup_cache(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    result = services.state.cleanup_expired_state()
    result["checked_at"] = utc_now()
    return result


def aggregate_analytics(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    limit = max(1, min(int(payload.get("limit", 1000)), 5000))
    events = services.app.GATEWAY_STORE.analytics(limit)
    def status_code(event: dict[str, Any]) -> int:
        if event.get("status_code") is not None:
            return int(event["status_code"])
        return 200 if event.get("success") is True else 500

    def event_path(event: dict[str, Any]) -> str:
        properties = event.get("properties") if isinstance(event.get("properties"), dict) else {}
        return str(event.get("path") or properties.get("path") or "unknown")

    status_counts = Counter(str(status_code(event)) for event in events)
    path_counts = Counter(event_path(event) for event in events)
    durations = [float(event["duration_ms"]) for event in events if isinstance(event.get("duration_ms"), (int, float))]
    successes = sum(1 for event in events if 200 <= status_code(event) < 400)
    summary = {
        "generated_at": utc_now(),
        "event_count": len(events),
        "success_count": successes,
        "failure_count": len(events) - successes,
        "success_rate": round(successes / len(events), 4) if events else 0.0,
        "average_duration_ms": round(sum(durations) / len(durations), 3) if durations else 0.0,
        "max_duration_ms": round(max(durations), 3) if durations else 0.0,
        "status_counts": dict(status_counts),
        "top_paths": [{"path": name, "count": count} for name, count in path_counts.most_common(20)],
    }
    write_json(state_path(services, "analytics-summary.json"), summary)
    return summary


def check_health(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    components: dict[str, Any] = {}
    components["redis"] = {"ok": bool(services.state.ping())}
    try:
        components["conversation_store"] = {"ok": True, "conversation_count": len(services.store.list_conversations())}
    except Exception as exc:
        components["conversation_store"] = {"ok": False, "error": str(exc)}
    try:
        records = services.app.load_vector_records()
        components["vector_store"] = {"ok": True, "record_count": len(records)}
    except Exception as exc:
        components["vector_store"] = {"ok": False, "error": str(exc)}
    upload_root = Path(getattr(services.app, "UPLOAD_ROOT", project_root(services) / "data/uploads"))
    components["upload_storage"] = {"ok": upload_root.exists() or upload_root.parent.exists(), "path": str(upload_root)}
    healthy = all(bool(item.get("ok")) for item in components.values())
    result = {"status": "ok" if healthy else "degraded", "checked_at": utc_now(), "components": components, "resources": resource_metrics(), "gpu": gpu_metrics(), "queues": services.state.queue_status() if hasattr(services.state, "queue_status") else {"available": False, "queues": {}, "totals": {}}}
    write_json(state_path(services, "health.json"), result)
    alert_email = os.getenv("AIOS_HEALTH_ALERT_EMAIL", "").strip()
    if not healthy and alert_email:
        result["alert_job_id"] = services.enqueue(EMAIL_QUEUE, {"to": alert_email, "subject": "AIOS worker health degraded", "body": json.dumps(result, indent=2)})
    return result


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def send_email(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    recipient = services.required(payload, "to")
    subject = services.required(payload, "subject")
    body = services.required(payload, "body")
    if not valid_email(recipient) or "\n" in subject or "\r" in subject:
        raise ValueError("Invalid email recipient or subject")
    host = os.getenv("AIOS_SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("AIOS_SMTP_HOST is required for email notifications")
    port = int(os.getenv("AIOS_SMTP_PORT", "587"))
    username = os.getenv("AIOS_SMTP_USERNAME", "").strip()
    password = os.getenv("AIOS_SMTP_PASSWORD", "")
    sender = os.getenv("AIOS_SMTP_FROM", username).strip()
    if not valid_email(sender):
        raise RuntimeError("AIOS_SMTP_FROM must be a valid email address")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, recipient, subject
    message.set_content(body)
    use_ssl = os.getenv("AIOS_SMTP_SSL", "false").lower() in {"1", "true", "yes", "on"}
    use_starttls = os.getenv("AIOS_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes", "on"}
    client_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with client_class(host, port, timeout=float(os.getenv("AIOS_SMTP_TIMEOUT", "20"))) as client:
        if use_starttls and not use_ssl:
            client.starttls(context=ssl.create_default_context())
        if username:
            client.login(username, password)
        client.send_message(message)
    return {"sent": True, "to": recipient, "subject": subject, "sent_at": utc_now()}


def backup_data(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    root = project_root(services)
    configured = Path(os.getenv("AIOS_BACKUP_DIR", "data/backups"))
    backup_dir = configured if configured.is_absolute() else root / configured
    backup_dir = backup_dir.resolve()
    if backup_dir != root and root not in backup_dir.parents:
        raise ValueError("AIOS_BACKUP_DIR must stay inside the project root")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_dir / f"aios-backup-{stamp}.zip"
    data_root = root / "data"
    included: list[str] = []
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if data_root.exists():
            for path in data_root.rglob("*"):
                if not path.is_file() or backup_dir == path.parent or backup_dir in path.parents:
                    continue
                relative = path.relative_to(root).as_posix()
                if Path(relative).name == ".env" or relative.endswith(".tmp"):
                    continue
                archive.write(path, relative)
                included.append(relative)
        manifest = json.dumps({"created_at": utc_now(), "files": included}, indent=2)
        archive.writestr("backup-manifest.json", manifest)
    retention = max(1, int(payload.get("retention", os.getenv("AIOS_BACKUP_RETENTION", "7"))))
    archives = sorted(backup_dir.glob("aios-backup-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    deleted = 0
    for old in archives[retention:]:
        old.unlink(missing_ok=True)
        deleted += 1
    return {"path": str(destination.relative_to(root)), "file_count": len(included), "size": destination.stat().st_size, "old_backups_deleted": deleted}


def workspace_code_records(root: Path, services: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        try:
            relative_path = path.relative_to(root)
            if not path.is_file() or path.suffix.lower() not in CODE_EXTENSIONS or EXCLUDED_PARTS.intersection(relative_path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = relative_path.as_posix()
        for chunk in services.app.chunk_document_text(text, chunk_size=1600, overlap=200):
            records.append({
                "id": f"code:{relative}:{chunk['id']}", "source_type": "code", "source_id": relative,
                "chunk_id": chunk["id"], "chunk_index": chunk["index"], "filename": relative,
                "document_type": path.suffix.lower().lstrip("."), "text": chunk["text"],
                "embedding": services.app.generate_embedding(chunk["text"]),
                "embedding_model": services.app.EMBEDDING_MODEL,
                "embedding_dimensions": services.app.EMBEDDING_DIMENSIONS,
                "metadata": {"source_path": str(path), "start_char": chunk["start_char"], "end_char": chunk["end_char"]},
                "created_at": utc_now(),
            })
    return records


def update_vector_index(payload: dict[str, Any], services: Any) -> dict[str, Any]:
    allowed = {"document", "code", "conversation", "memory"}
    requested = payload.get("targets") or sorted(allowed)
    targets = {str(item).lower() for item in requested}
    if not targets or not targets <= allowed:
        raise ValueError(f"Vector targets must be selected from: {', '.join(sorted(allowed))}")
    counts: dict[str, int] = {}
    artifacts = services.app.load_artifacts() if targets & {"document", "code"} else []
    artifact_records = [record for artifact in artifacts for record in services.app.vector_records_for_artifact(artifact)]
    if "document" in targets:
        records = [record for record in artifact_records if record.get("source_type") == "document"]
        services.app.replace_vector_source("document", records)
        counts["document"] = len(records)
    if "code" in targets:
        upload_code = [record for record in artifact_records if record.get("source_type") == "code"]
        records = [*upload_code, *workspace_code_records(monitored_root(payload, services), services)]
        services.app.replace_vector_source("code", records)
        counts["code"] = len(records)
    if "conversation" in targets:
        conversations = services.store.list_conversations()
        records = [
            services.app.vector_record_for_message(str(conversation["id"]), message, conversation.get("user_id"))
            for conversation in conversations for message in conversation.get("messages", [])
            if message.get("role") in {"user", "assistant"} and str(message.get("content") or "").strip()
        ]
        services.app.replace_vector_source("conversation", records)
        counts["conversation"] = len(records)
    if "memory" in targets:
        users = {str(item.get("user_id")) for item in services.store.list_conversations() if item.get("user_id")}
        records = services.app.vector_records_for_long_term_memory(services.store.get_long_term_memory(), None)
        for user_id in sorted(users):
            records.extend(services.app.vector_records_for_long_term_memory(services.store.get_long_term_memory(user_id), user_id))
        services.app.replace_vector_source("memory", records)
        counts["memory"] = len(records)
    return {"updated_at": utc_now(), "targets": sorted(targets), "counts": counts, "total_vectors": sum(counts.values())}


class Scheduler:
    def __init__(self, services: Any) -> None:
        self.services = services
        self.path = state_path(services, "scheduler.json")

    def schedules(self) -> dict[str, tuple[str, int, dict[str, Any]]]:
        defaults = {
            "git": (GIT_MONITOR_QUEUE, 30, {}),
            "files": (FILE_MONITOR_QUEUE, 60, {}),
            "cache": (CACHE_CLEANUP_QUEUE, 300, {}),
            "analytics": (ANALYTICS_QUEUE, 300, {}),
            "health": (HEALTH_QUEUE, 60, {}),
            "backup": (BACKUP_QUEUE, 86400, {}),
            "vector": (VECTOR_UPDATE_QUEUE, 900, {"targets": ["document", "conversation", "memory"]}),
        }
        return {
            name: (queue, max(0, int(os.getenv(f"AIOS_SCHEDULE_{name.upper()}_SECONDS", str(interval)))), payload)
            for name, (queue, interval, payload) in defaults.items()
        }

    def tick(self, now: float | None = None) -> dict[str, Any]:
        timestamp = float(now if now is not None else datetime.now(timezone.utc).timestamp())
        state = read_json(self.path, {"last_run": {}})
        last_run = state.get("last_run", {}) if isinstance(state, dict) else {}
        enqueued: list[dict[str, Any]] = []
        for name, (queue, interval, payload) in self.schedules().items():
            if interval <= 0 or timestamp - float(last_run.get(name, 0)) < interval:
                continue
            job_id = self.services.enqueue(queue, payload)
            if job_id:
                last_run[name] = timestamp
                enqueued.append({"name": name, "queue": queue, "job_id": job_id})
        write_json(self.path, {"updated_at": utc_now(), "last_run": last_run})
        return {"enqueued": enqueued, "count": len(enqueued)}