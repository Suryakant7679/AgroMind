import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(".env.local")
load_dotenv()

# Clean environment variables of spaces/quotes
for env_key in [
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY"
]:
    env_val = os.getenv(env_key)
    if env_val:
        os.environ[env_key] = env_val.strip().strip("'\"")


@lru_cache
def supabase_client() -> Client | None:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if url:
        url = url.strip().strip("'\"")
    if key:
        key = key.strip().strip("'\"")
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
    if url:
        url = url.strip().strip("'\"")
    if key:
        key = key.strip().strip("'\"")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def supabase_auth_configured() -> bool:
    url = _supabase_url()
    key = _anon_key()
    return bool(url and key)


def supabase_database_configured() -> bool:
    return bool(_supabase_url() and _database_key())


def _supabase_url() -> str | None:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    return url.strip().strip("'\"") if url else None


def _anon_key() -> str | None:
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    return key.strip().strip("'\"") if key else None


def _database_key() -> str | None:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or _anon_key()
    return key.strip().strip("'\"") if key else None


def _service_role_key() -> str | None:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    return key.strip().strip("'\"") if key else None


def is_email_delivery_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "error sending confirmation email" in message or "could not send otp email" in message


def _can_use_python_client(access_token: str | None = None) -> bool:
    if os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return True
    if not access_token:
        return True
    return False


def _rest_headers(key: str, bearer: str | None = None) -> dict[str, str]:
    if key:
        key = key.strip().strip("'\"")
    if bearer:
        bearer = bearer.strip().strip("'\"")

    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    # If a service role key is available on the backend, always use it for the
    # Authorization header to bypass RLS and avoid user JWT expiration issues.
    service_role = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if service_role:
        service_role = service_role.strip().strip("'\"")
        headers["Authorization"] = f"Bearer {service_role}"
    else:
        token = bearer or key
        if token and token.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {token}"
    return headers


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
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    response = httpx.post(
        endpoint,
        headers=headers,
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


def create_confirmed_user_with_password(email: str, password: str, full_name: str = "") -> dict:
    url = _supabase_url()
    service_key = _service_role_key()
    if not url or not service_key:
        raise RuntimeError("Supabase service role key is required for email delivery fallback.")

    endpoint = f"{url.rstrip('/')}/auth/v1/admin/users"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    response = httpx.post(
        endpoint,
        headers=headers,
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name or "AgroMind User"},
        },
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err = response.json()
            err_msg = err.get("error_description") or err.get("msg") or err.get("message") or "Could not create confirmed user."
        except Exception:
            err_msg = "Could not create confirmed user."
        raise RuntimeError(err_msg)

    payload = response.json()
    user = payload.get("user") or payload
    if not user.get("id") or not user.get("email"):
        raise RuntimeError("Supabase did not return a created user.")
    return {"id": user["id"], "email": user["email"], "access_token": None}


def sign_up_with_password(email: str, password: str, full_name: str = "", redirect_to: str | None = None) -> dict:
    client = supabase_auth_client()
    if client:
        try:
            options = {"data": {"full_name": full_name or "AgroMind User", "verification_method": "link"}}
            if redirect_to:
                options["email_redirect_to"] = redirect_to
            result = client.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    "options": options,
                }
            )
            user_id = result.user.id if (result and result.user) else None
            user_email = result.user.email if (result and result.user) else email
            access_token = result.session.access_token if (result and result.session) else None
            return {"id": user_id, "email": user_email, "access_token": access_token}
        except Exception as e:
            raise RuntimeError(str(e))

    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/signup"
    if redirect_to:
        endpoint = f"{endpoint}?redirect_to={quote(redirect_to, safe='')}"
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    response = httpx.post(
        endpoint,
        headers=headers,
        json={
            "email": email,
            "password": password,
            "data": {"full_name": full_name or "AgroMind User", "verification_method": "link"},
        },
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err_msg = response.json().get("error_description") or response.json().get("msg") or "Signup failed."
        except Exception:
            err_msg = "Signup failed."
        raise RuntimeError(err_msg)

    payload = response.json()
    user = payload.get("user") or payload
    user_id = None
    user_email = email
    if isinstance(user, dict):
        user_id = user.get("id")
        user_email = user.get("email") or email
    return {"id": user_id, "email": user_email, "access_token": payload.get("access_token") if isinstance(payload, dict) else None}


def send_signup_otp(email: str, full_name: str = "", redirect_to: str | None = None) -> None:
    url = _supabase_url()
    key = _anon_key()
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/otp"
    if redirect_to:
        endpoint = f"{endpoint}?redirect_to={quote(redirect_to, safe='')}"
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "email": email,
        "create_user": True,
        "data": {"full_name": full_name or "AgroMind User", "verification_method": "otp"},
        "options": {
            "data": {"full_name": full_name or "AgroMind User", "verification_method": "otp"}
        }
    }
    if redirect_to:
        payload["options"]["email_redirect_to"] = redirect_to

    response = httpx.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err_msg = response.json().get("error_description") or response.json().get("msg") or "Could not send OTP email."
        except Exception:
            err_msg = "Could not send OTP email."
        raise RuntimeError(err_msg)


def verify_signup_otp(email: str, token: str, otp_type: str = "signup") -> dict:
    client = supabase_auth_client()
    if client:
        try:
            result = client.auth.verify_otp({"email": email, "token": token, "type": otp_type})
            if not result.user:
                raise RuntimeError("Verification did not return a user.")
            access_token = result.session.access_token if result.session else None
            return {"id": result.user.id, "email": result.user.email, "access_token": access_token}
        except Exception as e:
            if otp_type in {"magiclink", "email"}:
                fallback_type = "email" if otp_type == "magiclink" else "magiclink"
                try:
                    result = client.auth.verify_otp({"email": email, "token": token, "type": fallback_type})
                    if result.user:
                        access_token = result.session.access_token if result.session else None
                        return {"id": result.user.id, "email": result.user.email, "access_token": access_token}
                except Exception:
                    pass
            raise RuntimeError(str(e))

    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/verify"
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"

    def do_post(t):
        return httpx.post(
            endpoint,
            headers=headers,
            json={
                "type": t,
                "email": email,
                "token": token,
            },
            timeout=20,
        )

    response = do_post(otp_type)
    if response.status_code >= 400 and otp_type in {"magiclink", "email"}:
        fallback_type = "email" if otp_type == "magiclink" else "magiclink"
        fb_response = do_post(fallback_type)
        if fb_response.status_code < 400:
            response = fb_response

    if response.status_code >= 400:
        try:
            err_msg = response.json().get("error_description") or response.json().get("msg") or "Verification failed."
        except Exception:
            err_msg = "Verification failed."
        raise RuntimeError(err_msg)

    payload = response.json()
    user = payload.get("user") or payload
    if not user.get("id") or not user.get("email"):
        raise RuntimeError("Supabase did not return a user.")
    return {"id": user["id"], "email": user["email"], "access_token": payload.get("access_token")}


def verify_email_token_hash(token_hash: str, verify_type: str = "email") -> dict:
    """Exchange a Supabase email confirmation token_hash for a user session."""
    url = _supabase_url()
    key = _anon_key()
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/verify"
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    response = httpx.post(
        endpoint,
        headers=headers,
        json={"type": verify_type, "token_hash": token_hash},
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err = response.json()
            err_msg = err.get("error_description") or err.get("msg") or "Token verification failed."
        except Exception:
            err_msg = "Token verification failed."
        raise RuntimeError(err_msg)

    payload = response.json()
    user = payload.get("user") or {}
    if not user.get("id") or not user.get("email"):
        raise RuntimeError("Verification succeeded but no user returned.")
    return {
        "id": user["id"],
        "email": user["email"],
        "access_token": payload.get("access_token"),
    }


def resend_signup_otp(email: str) -> None:
    """Resend a signup confirmation OTP for an already-registered (unconfirmed) user."""
    url = _supabase_url()
    key = _anon_key()
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/resend"
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    response = httpx.post(
        endpoint,
        headers=headers,
        json={"type": "signup", "email": email},
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err_msg = (
                response.json().get("error_description")
                or response.json().get("msg")
                or "Could not resend verification code."
            )
        except Exception:
            err_msg = "Could not resend verification code."
        raise RuntimeError(err_msg)


def update_user_password(access_token: str, password: str) -> None:
    """Set or update the password for the currently authenticated user using their access token."""
    url = _supabase_url()
    key = _anon_key()
    if not url or not key:
        raise RuntimeError("Supabase auth is not configured.")

    endpoint = f"{url.rstrip('/')}/auth/v1/user"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = httpx.put(
        endpoint,
        headers=headers,
        json={"password": password},
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            err_msg = (
                response.json().get("error_description")
                or response.json().get("msg")
                or "Failed to set password."
            )
        except Exception:
            err_msg = "Failed to set password."
        raise RuntimeError(err_msg)


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
    if client and _can_use_python_client(access_token):
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
        r1 = httpx.post(_rest_url("ai_outputs"), headers=_rest_headers(key, access_token), json=output_row, timeout=20)
        r1.raise_for_status()
    except Exception as exc:
        print(f"Error saving to ai_outputs via REST: {exc}")
        if 'r1' in locals():
            print(f"ai_outputs error response: {r1.status_code} - {r1.text}")
    try:
        r2 = httpx.post(_rest_url("usage_events"), headers=_rest_headers(key, access_token), json=usage_row, timeout=20)
        r2.raise_for_status()
    except Exception as exc:
        print(f"Error saving to usage_events via REST: {exc}")
        if 'r2' in locals():
            print(f"usage_events error response: {r2.status_code} - {r2.text}")


def fetch_recent_outputs(user_id: str | None = None, limit: int = 5, access_token: str | None = None) -> list[dict]:
    client = supabase_client()
    if client and _can_use_python_client(access_token):
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
    if client and _can_use_python_client(access_token):
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


def fetch_profile(user_id: str | None, access_token: str | None = None) -> dict | None:
    client = supabase_client()
    if not user_id:
        return None
    if client and _can_use_python_client(access_token):
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
    if client and _can_use_python_client(access_token):
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


def update_profile(user_id: str | None, profile_data: dict, access_token: str | None = None) -> None:
    if not user_id:
        return
    row = {**profile_data, "updated_at": datetime.now(UTC).isoformat()}
    client = supabase_client()
    if client and _can_use_python_client(access_token):
        try:
            client.table("profiles").update(row).eq("id", user_id).execute()
            return
        except Exception:
            pass
    key = _database_key()
    if not key:
        raise RuntimeError("Supabase credentials are not configured.")
    try:
        response = httpx.patch(
            _rest_url("profiles", f"id=eq.{quote(user_id)}"),
            headers=_rest_headers(key, access_token),
            json=row,
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"REST PATCH failed ({e.response.status_code}): {e.response.text}")


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
    if client and _can_use_python_client(access_token):
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
