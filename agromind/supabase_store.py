import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(".env.local")
load_dotenv()


@lru_cache
def supabase_client() -> Client | None:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


@lru_cache
def supabase_auth_client() -> Client | None:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def supabase_auth_configured() -> bool:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    return bool(url and key)


def supabase_database_configured() -> bool:
    return bool(_supabase_url() and _database_key())


def _supabase_url() -> str | None:
    return os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")


def _anon_key() -> str | None:
    return os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")


def _database_key() -> str | None:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or _anon_key()


def _rest_headers(key: str, bearer: str | None = None) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {bearer or key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest_url(table: str, query: str = "") -> str:
    url = _supabase_url()
    if not url:
        raise RuntimeError("Supabase URL is not configured.")
    suffix = f"?{query}" if query else ""
    return f"{url.rstrip('/')}/rest/v1/{table}{suffix}"


def sign_in_with_password(email: str, password: str) -> dict:
    client = supabase_auth_client()
    if client:
        result = client.auth.sign_in_with_password({"email": email, "password": password})
        access_token = result.session.access_token if result.session else None
        return {"id": result.user.id, "email": result.user.email, "access_token": access_token}

    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/token?grant_type=password"
    response = httpx.post(
        endpoint,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        json={"email": email, "password": password},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError("Invalid email or password.")

    payload = response.json()
    user = payload.get("user") or {}
    if not user.get("id") or not user.get("email"):
        raise RuntimeError("Supabase did not return a user.")
    return {"id": user["id"], "email": user["email"], "access_token": payload.get("access_token")}


def sign_up_with_password(email: str, password: str, full_name: str = "") -> dict:
    client = supabase_auth_client()
    if client:
        result = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"full_name": full_name or "AgroMind User"}},
            }
        )
        if not result.user:
            raise RuntimeError("Signup did not return a user.")
        access_token = result.session.access_token if result.session else None
        return {"id": result.user.id, "email": result.user.email, "access_token": access_token}

    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/signup"
    response = httpx.post(
        endpoint,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        json={
            "email": email,
            "password": password,
            "data": {"full_name": full_name or "AgroMind User"},
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError("Signup failed. This email may already exist or signup may be disabled.")

    payload = response.json()
    user = payload.get("user") or {}
    if not user.get("id") or not user.get("email"):
        raise RuntimeError("Supabase did not return a user.")
    return {"id": user["id"], "email": user["email"], "access_token": payload.get("access_token")}


def verify_signup_otp(email: str, token: str) -> dict:
    client = supabase_auth_client()
    if client:
        result = client.auth.verify_otp({"email": email, "token": token, "type": "signup"})
        if not result.user:
            raise RuntimeError("Verification did not return a user.")
        access_token = result.session.access_token if result.session else None
        return {"id": result.user.id, "email": result.user.email, "access_token": access_token}

    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/verify"
    response = httpx.post(
        endpoint,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        json={
            "type": "signup",
            "email": email,
            "token": token,
        },
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err_msg = response.json().get("error_description") or response.json().get("msg") or "Verification failed."
        except Exception:
            err_msg = "Verification failed."
        raise RuntimeError(err_msg)

    payload = response.json()
    user = payload.get("user") or {}
    if not user.get("id") or not user.get("email"):
        raise RuntimeError("Supabase did not return a user.")
    return {"id": user["id"], "email": user["email"], "access_token": payload.get("access_token")}


def insert_profile_if_missing(user_id: str, email: str, full_name: str = "") -> None:
    client = supabase_client()
    row = {
        "id": user_id,
        "email": email,
        "full_name": full_name or "AgroMind User",
    }
    if client:
        try:
            client.table("profiles").upsert(row).execute()
            return
        except Exception:
            pass

    key = _database_key()
    if not key:
        return
    try:
        httpx.post(_rest_url("profiles"), headers=_rest_headers(key), json=row, timeout=20)
    except Exception:
        pass


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
) -> None:
    tokens_used = max(1, input_tokens + (len(output) // 4))
    output_row = {
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
    client = supabase_client()
    if client:
        try:
            client.table("ai_outputs").insert(output_row).execute()
            client.table("usage_events").insert(usage_row).execute()
            return
        except Exception:
            pass

    key = _database_key()
    if not key:
        return
    try:
        httpx.post(_rest_url("ai_outputs"), headers=_rest_headers(key, access_token), json=output_row, timeout=20)
        httpx.post(_rest_url("usage_events"), headers=_rest_headers(key, access_token), json=usage_row, timeout=20)
    except Exception:
        pass


def fetch_recent_outputs(user_id: str | None = None, limit: int = 5, access_token: str | None = None) -> list[dict]:
    client = supabase_client()
    if client:
        query = client.table("ai_outputs").select("*").order("created_at", desc=True).limit(limit)
        if user_id:
            query = query.eq("user_id", user_id)
        try:
            return query.execute().data or []
        except Exception:
            pass

    key = _database_key()
    if not key:
        return []
    params = [f"select=*", "order=created_at.desc", f"limit={limit}"]
    if user_id:
        params.append(f"user_id=eq.{quote(user_id)}")
    try:
        response = httpx.get(_rest_url("ai_outputs", "&".join(params)), headers=_rest_headers(key, access_token), timeout=20)
        return response.json() if response.status_code < 400 else []
    except Exception:
        return []


def fetch_usage_events(user_id: str | None, access_token: str | None = None, limit: int = 1000) -> list[dict]:
    if not user_id:
        return []
    client = supabase_client()
    if client:
        try:
            return (
                client.table("usage_events")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
                .data
                or []
            )
        except Exception:
            pass

    key = _database_key()
    if not key:
        return []
    params = f"select=*&user_id=eq.{quote(user_id)}&order=created_at.desc&limit={limit}"
    try:
        response = httpx.get(_rest_url("usage_events", params), headers=_rest_headers(key, access_token), timeout=20)
        return response.json() if response.status_code < 400 else []
    except Exception:
        return []


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
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def fetch_profile(user_id: str | None, access_token: str | None = None) -> dict | None:
    client = supabase_client()
    if not user_id:
        return None
    if client:
        try:
            data = client.table("profiles").select("*").eq("id", user_id).single().execute().data
            return data
        except Exception:
            pass

    key = _database_key()
    if not key:
        return None
    try:
        response = httpx.get(_rest_url("profiles", f"select=*&id=eq.{quote(user_id)}&limit=1"), headers=_rest_headers(key, access_token), timeout=20)
        if response.status_code >= 400:
            return None
        rows = response.json()
        return rows[0] if rows else None
    except Exception:
        return None


def fetch_profiles(limit: int = 25) -> list[dict]:
    client = supabase_client()
    if client:
        try:
            return client.table("profiles").select("email,full_name,organization,role,plan").order("created_at", desc=True).limit(limit).execute().data or []
        except Exception:
            pass

    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return []
    try:
        response = httpx.get(
            _rest_url("profiles", f"select=email,full_name,organization,role,plan&order=created_at.desc&limit={limit}"),
            headers=_rest_headers(key),
            timeout=20,
        )
        return response.json() if response.status_code < 400 else []
    except Exception:
        return []


def update_profile_plan(user_id: str | None, plan: str, access_token: str | None = None) -> None:
    if not user_id:
        return
    row = {"plan": plan, "updated_at": datetime.now(UTC).isoformat()}
    client = supabase_client()
    if client:
        try:
            client.table("profiles").update(row).eq("id", user_id).execute()
            return
        except Exception:
            pass
    key = _database_key()
    if not key:
        return
    try:
        httpx.patch(_rest_url("profiles", f"id=eq.{quote(user_id)}"), headers=_rest_headers(key, access_token), json=row, timeout=20)
    except Exception:
        pass


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
        "provider": "razorpay",
        "provider_order_id": provider_order_id,
        "provider_payment_id": provider_payment_id,
        "status": status,
    }
    client = supabase_client()
    if client:
        try:
            client.table("payments").insert(row).execute()
            return
        except Exception:
            pass
    key = _database_key()
    if not key:
        return
    try:
        httpx.post(_rest_url("payments"), headers=_rest_headers(key), json=row, timeout=20)
    except Exception:
        pass


def save_subscription(user_id: str | None, plan: str, access_token: str | None = None) -> None:
    if not user_id:
        return
    row = {
        "user_id": user_id,
        "plan": plan,
        "status": "active",
        "current_period_end": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    client = supabase_client()
    if client:
        try:
            client.table("subscriptions").insert(row).execute()
            return
        except Exception:
            pass
    key = _database_key()
    if not key:
        return
    try:
        httpx.post(_rest_url("subscriptions"), headers=_rest_headers(key, access_token), json=row, timeout=20)
    except Exception:
        pass
