from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from app.store import utc_now


class GatewayError(ValueError):
    def __init__(self, status: int, code: str, message: str, details: list[str] | None = None) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    roles: tuple[str, ...] = ("user",)
    session_id: str = ""

    def has_role(self, *roles: str) -> bool:
        return bool(set(self.roles) & set(roles))


@dataclass(frozen=True)
class FieldSpec:
    types: tuple[type, ...]
    required: bool = False
    allow_blank: bool = True
    max_length: int | None = None


class RequestSchema:
    def __init__(self, fields: Mapping[str, FieldSpec], allow_extra: bool = False) -> None:
        self.fields = dict(fields)
        self.allow_extra = allow_extra

    def validate(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise GatewayError(400, "invalid_request", "Request body must be a JSON object.")
        issues: list[str] = []
        if not self.allow_extra:
            issues.extend(f"Unknown field: {key}" for key in payload if key not in self.fields)
        for name, spec in self.fields.items():
            if name not in payload:
                if spec.required:
                    issues.append(f"Missing required field: {name}")
                continue
            value = payload[name]
            if isinstance(value, bool) and bool not in spec.types:
                issues.append(f"Field {name} has the wrong type.")
                continue
            if not isinstance(value, spec.types):
                issues.append(f"Field {name} has the wrong type.")
                continue
            if isinstance(value, str):
                if not spec.allow_blank and not value.strip():
                    issues.append(f"Field {name} cannot be blank.")
                if spec.max_length is not None and len(value) > spec.max_length:
                    issues.append(f"Field {name} exceeds {spec.max_length} characters.")
        if issues:
            raise GatewayError(400, "schema_validation_failed", "Request validation failed.", issues)
        return dict(payload)


class ResponseSchema(RequestSchema):
    def validate(self, payload: Any) -> dict[str, Any]:
        try:
            return super().validate(payload)
        except GatewayError as exc:
            raise GatewayError(500, "invalid_response", "Server response did not match its schema.", exc.details) from exc


AUTH_SCHEMA = RequestSchema({
    "email": FieldSpec((str,), True, False, 320),
    "password": FieldSpec((str,), True, False, 1024),
    "display_name": FieldSpec((str,), False, True, 120),
})
LOGIN_SCHEMA = RequestSchema({
    "email": FieldSpec((str,), True, False, 320),
    "password": FieldSpec((str,), True, False, 1024),
})
CHAT_SCHEMA = RequestSchema({
    "message": FieldSpec((str,), True, False, 100_000),
    "conversation_id": FieldSpec((str, type(None))),
    "thread_id": FieldSpec((str, type(None))),
    "session_id": FieldSpec((str, type(None))),
    "artifact_ids": FieldSpec((list,)),
    "variables": FieldSpec((dict,)),
    "stream": FieldSpec((bool,)),
}, allow_extra=False)
PLAN_SCHEMA = RequestSchema({
    "objective": FieldSpec((str,), True, False, 8_000),
    "context": FieldSpec((dict,)),
})
AUTH_RESPONSE_SCHEMA = ResponseSchema({
    "access_token": FieldSpec((str,), True, False),
    "token_type": FieldSpec((str,), True, False),
    "expires_in": FieldSpec((int,), True),
    "user": FieldSpec((dict,), True),
    "session": FieldSpec((dict,), True),
})
SESSION_RESPONSE_SCHEMA = ResponseSchema({"session": FieldSpec((dict,), True)})
CONVERSATION_SCHEMA = RequestSchema({"session_id": FieldSpec((str, type(None)))})
THREAD_SCHEMA = RequestSchema({"title": FieldSpec((str,), False, True, 200)})
SESSION_SCHEMA = RequestSchema({
    "session_id": FieldSpec((str, type(None))), "active_project": FieldSpec((str, type(None)), max_length=500),
    "current_workspace": FieldSpec((dict, type(None))), "running_task": FieldSpec((str, type(None)), max_length=8_000),
    "active_file": FieldSpec((str, type(None)), max_length=2_000), "open_files": FieldSpec((list, type(None))),
    "active_tool": FieldSpec((str, type(None)), max_length=500), "terminal_output": FieldSpec((str, type(None)), max_length=100_000),
    "browser_results": FieldSpec((str, type(None)), max_length=100_000), "mcp_outputs": FieldSpec((str, type(None)), max_length=100_000),
    "developer_instructions": FieldSpec((str, type(None)), max_length=100_000), "user_preferences": FieldSpec((dict, type(None))),
})
MEMORY_SCHEMA = RequestSchema({
    "user_preferences": FieldSpec((dict, type(None))), "coding_style": FieldSpec((list, type(None))),
    "projects": FieldSpec((list, type(None))), "commands": FieldSpec((list, type(None))),
    "learned_behavior": FieldSpec((list, type(None))),
})


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class JWTService:
    def __init__(self, secret: str, issuer: str = "aios", audience: str = "aios-api", ttl_seconds: int = 3600) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("JWT secret must contain at least 32 bytes")
        self.secret = secret.encode("utf-8")
        self.issuer = issuer
        self.audience = audience
        self.ttl_seconds = max(60, ttl_seconds)

    def issue(self, principal: Principal, now: int | None = None) -> str:
        now = int(time.time()) if now is None else now
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": principal.user_id,
            "email": principal.email,
            "roles": list(principal.roles),
            "sid": principal.session_id,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "nbf": now,
            "exp": now + self.ttl_seconds,
            "jti": str(uuid4()),
        }
        encoded = f"{_b64encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64encode(json.dumps(payload, separators=(',', ':')).encode())}"
        signature = hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_b64encode(signature)}"

    def verify(self, token: str, now: int | None = None) -> Principal:
        try:
            header_part, payload_part, signature_part = token.split(".")
            header = json.loads(_b64decode(header_part))
            payload = json.loads(_b64decode(payload_part))
            signature = _b64decode(signature_part)
        except (ValueError, TypeError, AttributeError, binascii.Error, json.JSONDecodeError, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise GatewayError(401, "invalid_token", "Bearer token is malformed.") from exc
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise GatewayError(401, "invalid_token", "Bearer token uses an unsupported algorithm.")
        signed = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(self.secret, signed, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise GatewayError(401, "invalid_token", "Bearer token signature is invalid.")
        now = int(time.time()) if now is None else now
        if payload.get("iss") != self.issuer or payload.get("aud") != self.audience:
            raise GatewayError(401, "invalid_token", "Bearer token issuer or audience is invalid.")
        if not isinstance(payload.get("exp"), int) or now >= payload["exp"]:
            raise GatewayError(401, "token_expired", "Bearer token has expired.")
        if not isinstance(payload.get("nbf"), int) or now < payload["nbf"]:
            raise GatewayError(401, "invalid_token", "Bearer token is not active yet.")
        user_id = str(payload.get("sub") or "").strip()
        if not user_id:
            raise GatewayError(401, "invalid_token", "Bearer token subject is missing.")
        roles = payload.get("roles") if isinstance(payload.get("roles"), list) else []
        return Principal(user_id, str(payload.get("email") or ""), tuple(str(role) for role in roles), str(payload.get("sid") or ""))


def password_hash(password: str, iterations: int = 310_000) -> str:
    if len(password) < 8:
        raise GatewayError(400, "weak_password", "Password must contain at least 8 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64decode(salt), int(iterations))
        return hmac.compare_digest(_b64encode(digest), expected)
    except (ValueError, TypeError):
        return False


class GatewayStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"jwt_secret": secrets.token_urlsafe(48), "users": [], "analytics": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        payload.setdefault("jwt_secret", secrets.token_urlsafe(48))
        payload.setdefault("users", [])
        payload.setdefault("analytics", [])
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def jwt_secret(self) -> str:
        with self._lock:
            payload = self._load()
            self._save(payload)
            return str(payload["jwt_secret"])

    def register(self, email: str, password: str, display_name: str = "") -> dict[str, Any]:
        normalized = email.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise GatewayError(400, "invalid_email", "A valid email address is required.")
        with self._lock:
            payload = self._load()
            if any(user["email"].casefold() == normalized for user in payload["users"]):
                raise GatewayError(409, "email_exists", "An account with this email already exists.")
            admin_emails = {item.strip().casefold() for item in os.getenv("AIOS_ADMIN_EMAILS", "").split(",") if item.strip()}
            user = {
                "id": str(uuid4()), "email": normalized, "display_name": display_name.strip(),
                "password_hash": password_hash(password), "status": "active",
                "roles": ["admin", "user"] if normalized in admin_emails else ["user"],
                "created_at": utc_now(), "updated_at": utc_now(),
            }
            payload["users"].append(user)
            self._save(payload)
            return self.public_user(user)

    def authenticate(self, email: str, password: str) -> dict[str, Any]:
        with self._lock:
            user = next((item for item in self._load()["users"] if item["email"].casefold() == email.strip().casefold()), None)
        if not user or not password_matches(password, str(user.get("password_hash") or "")):
            raise GatewayError(401, "invalid_credentials", "Email or password is incorrect.")
        if user.get("status") != "active":
            raise GatewayError(403, "account_disabled", "This account is not active.")
        return self.public_user(user)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            user = next((item for item in self._load()["users"] if item["id"] == user_id), None)
        return self.public_user(user) if user else None

    def record_event(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            payload = self._load()
            payload["analytics"] = [*payload["analytics"][-4999:], {**event, "occurred_at": utc_now()}]
            self._save(payload)

    def analytics(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._load()["analytics"][-max(1, min(limit, 1000)):]))

    @staticmethod
    def public_user(user: Mapping[str, Any]) -> dict[str, Any]:
        return {key: user.get(key) for key in ("id", "email", "display_name", "status", "roles", "created_at", "updated_at")}


class PostgreSQLGatewayStore(GatewayStore):
    """Gateway identity and analytics store backed by the existing SQL schema."""

    def __init__(self, database_url: str, secret_path: str | Path) -> None:
        if not database_url.strip():
            raise ValueError("database_url is required")
        super().__init__(secret_path)
        self.database_url = database_url

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError('PostgreSQL gateway storage requires psycopg. Install "psycopg[binary]".') from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
        preferences = row.get("preferences") if isinstance(row.get("preferences"), dict) else {}
        return {
            "id": str(row["id"]), "email": str(row["email"]),
            "display_name": str(row.get("display_name") or ""), "status": str(row.get("status") or "active"),
            "roles": list(preferences.get("roles") or ["user"]),
            "created_at": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
            "updated_at": row.get("updated_at").isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
        }

    def register(self, email: str, password: str, display_name: str = "") -> dict[str, Any]:
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        normalized = email.strip().casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise GatewayError(400, "invalid_email", "A valid email address is required.")
        admin_emails = {item.strip().casefold() for item in os.getenv("AIOS_ADMIN_EMAILS", "").split(",") if item.strip()}
        roles = ["admin", "user"] if normalized in admin_emails else ["user"]
        try:
            with self._connect() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        """INSERT INTO users (email, display_name, password_hash, status, preferences)
                           VALUES (%s, %s, %s, 'active', %s)
                           RETURNING id, email, display_name, status, preferences, created_at, updated_at""",
                        (normalized, display_name.strip(), password_hash(password), Jsonb({"roles": roles})),
                    )
                    row = cursor.fetchone()
                connection.commit()
        except Exception as exc:
            if "unique" in str(exc).casefold() or "duplicate" in str(exc).casefold():
                raise GatewayError(409, "email_exists", "An account with this email already exists.") from exc
            raise
        return self._public_row(row)

    def authenticate(self, email: str, password: str) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT id, email, display_name, password_hash, status, preferences, created_at, updated_at
                       FROM users WHERE lower(email) = lower(%s)""",
                    (email.strip(),),
                )
                row = cursor.fetchone()
        if not row or not password_matches(password, str(row.get("password_hash") or "")):
            raise GatewayError(401, "invalid_credentials", "Email or password is incorrect.")
        if row.get("status") != "active":
            raise GatewayError(403, "account_disabled", "This account is not active.")
        return self._public_row(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        from psycopg.rows import dict_row

        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT id, email, display_name, status, preferences, created_at, updated_at FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
        return self._public_row(row) if row else None

    def record_event(self, event: Mapping[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        standard = {"user_id", "session_id", "event_name", "event_category", "request_id", "duration_ms", "status_code"}
        try:
            request_id = str(uuid4()) if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(event.get("request_id") or "")) else event.get("request_id")
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO analytics (
                               user_id, session_id, event_name, event_category, request_id,
                               duration_ms, success, properties
                           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            event.get("user_id"), event.get("session_id"), event.get("event_name", "api_request"),
                            event.get("event_category", "gateway"), request_id, event.get("duration_ms"),
                            200 <= int(event.get("status_code", 500)) < 400,
                            Jsonb({key: value for key, value in event.items() if key not in standard}),
                        ),
                    )
                connection.commit()
        except Exception:
            # Telemetry must never break an API response.
            return

    def analytics(self, limit: int = 100) -> list[dict[str, Any]]:
        from psycopg.rows import dict_row

        with self._connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT id, user_id, session_id, event_name, event_category, request_id,
                              duration_ms, success, properties, occurred_at
                       FROM analytics ORDER BY occurred_at DESC LIMIT %s""",
                    (max(1, min(limit, 1000)),),
                )
                rows = cursor.fetchall()
        return [
            {
                **dict(row), "id": str(row["id"]),
                "user_id": str(row["user_id"]) if row.get("user_id") else None,
                "session_id": str(row["session_id"]) if row.get("session_id") else None,
                "request_id": str(row["request_id"]) if row.get("request_id") else None,
                "occurred_at": row["occurred_at"].isoformat() if hasattr(row.get("occurred_at"), "isoformat") else row.get("occurred_at"),
            }
            for row in rows
        ]


def create_gateway_store(root: Path) -> GatewayStore:
    path = root / os.getenv("AIOS_GATEWAY_DATA_FILE", "data/gateway.json")
    backend = os.getenv("AIOS_STORAGE_BACKEND", "auto").strip().lower()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if backend == "postgres" or (backend == "auto" and database_url):
        return PostgreSQLGatewayStore(database_url, path)
    return GatewayStore(path)


def normalize_api_path(path: str) -> tuple[str, str]:
    match = re.match(r"^/api/v(\d+)(/.*)?$", path)
    if not match:
        return path, "1"
    version = match.group(1)
    if version != "1":
        raise GatewayError(404, "unsupported_api_version", f"API version v{version} is not supported.")
    return "/api" + (match.group(2) or ""), version


def bearer_token(header: str) -> str | None:
    if not header.strip():
        return None
    scheme, separator, token = header.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token.strip():
        raise GatewayError(401, "invalid_authorization", "Authorization must use the Bearer scheme.")
    return token.strip()


def require_owner(resource: Mapping[str, Any], principal: Principal | None) -> None:
    owner = str(resource.get("user_id") or "")
    if principal is not None and (not owner or owner != principal.user_id) and not principal.has_role("admin"):
        raise GatewayError(403, "forbidden", "You do not have permission to access this resource.")


def error_payload(error: GatewayError, request_id: str = "") -> dict[str, Any]:
    return {"error": {"code": error.code, "message": error.message, "details": error.details}, "request_id": request_id}
