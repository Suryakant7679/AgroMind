"""PostgreSQL persistence and password authentication for the AgroMind portal."""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from contextlib import contextmanager
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv()
_initialized = set()
_schema_lock = Lock()


def database_url():
    return os.getenv("AGROMIND_DATABASE_URL") or os.getenv("DATABASE_URL", "")


def postgres_auth_configured():
    return bool(database_url())


postgres_database_configured = postgres_auth_configured


@contextmanager
def connection():
    url = database_url()
    if not url:
        raise RuntimeError("Set DATABASE_URL to your local PostgreSQL database in .env.")
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with _schema_lock:
                if url not in _initialized:
                    conn.execute(Path(__file__).with_name("schema.sql").read_text())
                    conn.commit()
                    _initialized.add(url)
            yield conn
    except psycopg.OperationalError as exc:
        raise RuntimeError("Cannot connect to PostgreSQL. Check DATABASE_URL and that PostgreSQL is running.") from exc


def _normalize(row):
    if row is None:
        return None
    return {k: str(v) if isinstance(v, uuid.UUID) else v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}


def _insert(conn, table, row):
    query = sql.SQL("INSERT INTO agromind.{} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, row)),
        sql.SQL(',').join(sql.Placeholder() for _ in row))
    values = [Jsonb(v) if isinstance(v, dict) else v for v in row.values()]
    return _normalize(conn.execute(query, values).fetchone())


def _rows(table, filters=None, limit=1000):
    if not database_url():
        return []
    filters = filters or {}
    query = sql.SQL("SELECT * FROM agromind.{} WHERE ").format(sql.Identifier(table))
    query += sql.SQL(' AND ').join(sql.SQL('{} = %s').format(sql.Identifier(k)) for k in filters) if filters else sql.SQL('TRUE')
    query += sql.SQL(' ORDER BY created_at DESC LIMIT %s')
    with connection() as conn:
        return [_normalize(r) for r in conn.execute(query, [*filters.values(), max(1, min(int(limit), 10000))]).fetchall()]


def _update(table, record_id, values):
    query = sql.SQL('UPDATE agromind.{} SET {} WHERE id = %s RETURNING *').format(
        sql.Identifier(table), sql.SQL(',').join(sql.SQL('{} = %s').format(sql.Identifier(k)) for k in values))
    with connection() as conn:
        return _normalize(conn.execute(query, [*[Jsonb(v) if isinstance(v, dict) else v for v in values.values()], record_id]).fetchone())


def _hash_password(password, salt=None):
    if len(password) < 6 or len(password) > 1024:
        raise ValueError("Password must contain 6 to 1024 characters.")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def create_confirmed_user_with_password(email, password, full_name=""):
    email = email.strip().lower()
    if '@' not in email or len(email) > 254:
        raise ValueError("Enter a valid email address.")
    user_id = str(uuid.uuid4())
    hashed = _hash_password(password)
    try:
        with connection() as conn:
            _insert(conn, 'users', dict(id=user_id, email=email, password_hash=hashed))
            _insert(conn, 'profiles', dict(id=user_id, email=email, full_name=full_name or 'AgroMind User'))
    except psycopg.errors.UniqueViolation:
        raise ValueError("An account with this email already exists. Please log in.") from None
    return dict(id=user_id, email=email, access_token=None)


def sign_in_with_password(email, password):
    with connection() as conn:
        row = conn.execute('SELECT * FROM agromind.users WHERE email = %s', (email.strip().lower(),)).fetchone()
        stored = row['password_hash'] if row else _hash_password('dummy-password')
        try:
            valid = hmac.compare_digest(_hash_password(password, stored.split('$')[2]), stored)
        except (ValueError, IndexError):
            valid = False
        if not row or not valid:
            raise ValueError("Invalid email or password.")
        token = secrets.token_urlsafe(32)
        conn.execute('DELETE FROM agromind.sessions WHERE expires_at <= now()')
        conn.execute('INSERT INTO agromind.sessions VALUES (%s, %s, %s)',
                     (hashlib.sha256(token.encode()).hexdigest(), row['id'], datetime.now(UTC) + timedelta(days=14)))
        return dict(id=str(row['id']), email=row['email'], access_token=token)


def session_user(token):
    if not token or not database_url():
        return None
    with connection() as conn:
        row = conn.execute('SELECT u.id, u.email FROM agromind.sessions s JOIN agromind.users u ON u.id = s.user_id WHERE s.token_hash = %s AND s.expires_at > now()',
                           (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return {**_normalize(row), 'access_token': token} if row else None


def revoke_session(token):
    if token:
        with connection() as conn:
            conn.execute('DELETE FROM agromind.sessions WHERE token_hash = %s', (hashlib.sha256(token.encode()).hexdigest(),))


def update_user_password(access_token, password):
    user = session_user(access_token)
    if not user:
        raise ValueError("Please log in again.")
    with connection() as conn:
        conn.execute('UPDATE agromind.users SET password_hash = %s WHERE id = %s', (_hash_password(password), user['id']))
        conn.execute('DELETE FROM agromind.sessions WHERE user_id = %s', (user['id'],))


def insert_profile_if_missing(user_id, email, full_name=""):
    with connection() as conn:
        conn.execute('INSERT INTO agromind.profiles (id,email,full_name) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING',
                     (user_id, email, full_name or 'AgroMind User'))



def save_output(
    user_id: str | None,
    domain_id: str,
    tool_id: str,
    fields: dict,
    output: str,
    provider: str,
    input_tokens: int = 0,
    credits_used: int = 0,
    cost_cents: int = 0,
    access_token: str | None = None,
) -> str | None:
    tokens_used = max(1, input_tokens + (len(output) // 4))
    output_id = str(uuid.uuid4())
    output_row = {
        "id": output_id,
        "user_id": user_id,
        "domain": domain_id,
        "tool": tool_id,
        "prompt": fields,
        "output_markdown": output,
        "tokens_used": tokens_used,
    }
    usage_row = {
        "user_id": user_id,
        "domain": domain_id,
        "tool": tool_id,
        "provider": provider,
        "tokens_used": tokens_used,
        "credits_used": credits_used,
        "cost_cents": cost_cents,
    }
    with connection() as conn:
        _insert(conn, "ai_outputs", output_row)
        _insert(conn, "usage_events", usage_row)
    return output_id


def create_agent_action_draft(
    user_id: str,
    source_output_id: str,
    action_type: str,
    provider: str,
    draft_payload: dict,
    access_token: str | None = None,
) -> dict | None:
    row = {
        "user_id": user_id,
        "source_output_id": source_output_id,
        "action_type": action_type,
        "provider": provider,
        "draft_payload": draft_payload,
        "status": "pending",
    }
    with connection() as conn:
        return _insert(conn, "agent_action_drafts", row)


def save_agent_action_run(
    draft_id: str,
    user_id: str,
    provider: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    access_token: str | None = None,
) -> None:
    row = {
        "draft_id": draft_id,
        "user_id": user_id,
        "provider": provider,
        "status": status,
        "result": result or {},
        "error": error,
    }
    with connection() as conn:
        return _insert(conn, "agent_action_runs", row)


def save_agent_memory(
    user_id: str | None,
    agent: str,
    session_id: str,
    role: str,
    content: str,
    access_token: str | None = None,
) -> None:
    if not user_id:
        return
    row = {
        "user_id": user_id,
        "agent": agent,
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    with connection() as conn:
        return _insert(conn, "agent_memory", row)


def save_payment(
    user_id: str | None,
    plan: str,
    amount_paise: int,
    provider_order_id: str,
    provider_payment_id: str = "",
    status: str = "created",
) -> None:
    if not user_id:
        return
    row = {
        "user_id": user_id,
        "plan": plan,
        "amount_paise": amount_paise,
        "provider": "upi" if provider_order_id.startswith("upipay-") else ("sandbox" if provider_order_id.startswith("sandbox-") else "razorpay"),
        "provider_order_id": provider_order_id,
        "provider_payment_id": provider_payment_id,
        "status": status,
    }
    with connection() as conn:
        return _insert(conn, "payments", row)


def save_subscription(user_id: str | None, plan: str, access_token: str | None = None) -> None:
    if not user_id:
        return
    row = {
        "user_id": user_id,
        "plan": plan,
        "status": "active",
        "current_period_end": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    with connection() as conn:
        return _insert(conn, "subscriptions", row)


def usage_summary(user_id: str | None, access_token: str | None = None) -> dict:
    events = fetch_usage_events(user_id, access_token)
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    summary = {
        "requests_today": 0,
        "requests_this_month": 0,
        "tokens_this_month": 0,
        "credits_this_month": 0,
        "cost_cents_this_month": 0,
        "domain_rows": {},
        "provider_rows": {},
    }

    for event in events:
        created = _parse_time(event.get("created_at"))
        if not created or created < month_start:
            continue
        tokens = int(event.get("tokens_used") or 0)
        credits = int(event.get("credits_used") or 0)
        cost_cents = int(event.get("cost_cents") or 0)
        domain = event.get("domain") or "unknown"
        provider = event.get("provider") or "unknown"
        summary["requests_this_month"] += 1
        summary["tokens_this_month"] += tokens
        summary["credits_this_month"] += credits
        summary["cost_cents_this_month"] += cost_cents
        summary["domain_rows"].setdefault(domain, {"requests": 0, "tokens": 0, "credits": 0})
        summary["domain_rows"][domain]["requests"] += 1
        summary["domain_rows"][domain]["tokens"] += tokens
        summary["domain_rows"][domain]["credits"] += credits
        summary["provider_rows"].setdefault(provider, {"requests": 0, "tokens": 0, "credits": 0})
        summary["provider_rows"][provider]["requests"] += 1
        summary["provider_rows"][provider]["tokens"] += tokens
        summary["provider_rows"][provider]["credits"] += credits
        if created >= day_start:
            summary["requests_today"] += 1
    return summary

def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Normalize format for multi-python version compatibility
        s = value.replace(" ", "T").replace("Z", "+00:00")
        plus_idx = s.rfind("+")
        minus_idx = s.rfind("-")
        idx = max(plus_idx, minus_idx)
        if idx > 10:
            tz_part = s[idx:]
            if ":" not in tz_part:
                s = s[:idx] + tz_part + ":00"
        return datetime.fromisoformat(s).astimezone(UTC)
    except Exception:
        try:
            # Resilient naive substring fallback
            s = value.replace(" ", "T")
            return datetime.fromisoformat(s[:19]).replace(tzinfo=UTC)
        except Exception:
            return None


def fetch_profile(user_id, access_token=None):
    rows = _rows('profiles', {'id': user_id}, 1) if user_id else []
    return rows[0] if rows else None


def fetch_profiles(limit=25):
    return _rows('profiles', limit=limit)


def fetch_recent_outputs(user_id=None, limit=5, access_token=None):
    return _rows('ai_outputs', {'user_id': user_id} if user_id else {}, limit)


def fetch_output_by_id(output_id, access_token=None):
    try:
        uuid.UUID(str(output_id))
    except ValueError:
        return None
    filters = {'id': output_id}
    if access_token:
        user = session_user(access_token)
        if not user:
            return None
        filters['user_id'] = user['id']
    rows = _rows('ai_outputs', filters, 1)
    return rows[0] if rows else None


def fetch_usage_events(user_id, access_token=None, limit=1000):
    return _rows('usage_events', {'user_id': user_id}, limit) if user_id else []


def fetch_agent_memory(user_id, agent, session_id, limit=20, access_token=None):
    return list(reversed(_rows('agent_memory', dict(user_id=user_id, agent=agent, session_id=session_id), limit))) if user_id else []


def fetch_agent_action_draft(draft_id, access_token=None):
    filters = {'id': draft_id}
    if access_token:
        user = session_user(access_token)
        if not user:
            return None
        filters['user_id'] = user['id']
    rows = _rows('agent_action_drafts', filters, 1)
    return rows[0] if rows else None


def update_agent_action_draft(draft_id, values, access_token=None):
    if not fetch_agent_action_draft(draft_id, access_token):
        return None
    allowed = {'status', 'draft_payload', 'provider', 'action_type'}
    return _update('agent_action_drafts', draft_id, {**{k:v for k,v in values.items() if k in allowed}, 'updated_at': datetime.now(UTC)})


def update_profile_plan(user_id, plan, access_token=None):
    if user_id:
        _update('profiles', user_id, dict(plan=plan, updated_at=datetime.now(UTC)))


def update_profile(user_id, profile_data, access_token=None):
    if user_id:
        allowed = {'full_name', 'organization', 'role'}
        if profile_data.get('role', '').lower() == 'admin':
            current = fetch_profile(user_id) or {}
            if current.get('role') != 'admin':
                raise ValueError('Administrator access cannot be assigned from the profile page.')
        _update('profiles', user_id, {**{k:v for k,v in profile_data.items() if k in allowed}, 'updated_at': datetime.now(UTC)})
