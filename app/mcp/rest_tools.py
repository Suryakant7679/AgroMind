from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.mcp.browser_tools import validate_public_url


BLOCKED_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "proxy-authorization"}


def _allowed_hosts() -> set[str]:
    return {item.strip().lower() for item in os.getenv("AIOS_MCP_REST_HOSTS", "").split(",") if item.strip()}


def validate_rest_request(method: str, url: str, headers: dict[str, str] | None = None) -> tuple[str, str, dict[str, str]]:
    method = method.strip().upper()
    write_enabled = os.getenv("AIOS_MCP_REST_WRITE", "false").lower() == "true"
    allowed_methods = {"GET", "HEAD", "OPTIONS"} | ({"POST", "PUT", "PATCH", "DELETE"} if write_enabled else set())
    if method not in allowed_methods:
        raise PermissionError("REST mutations are disabled; set AIOS_MCP_REST_WRITE=true to enable them")
    url = validate_public_url(url)
    hosts = _allowed_hosts()
    if hosts and (urlparse(url).hostname or "").lower() not in hosts:
        raise PermissionError("URL host is not in AIOS_MCP_REST_HOSTS")
    cleaned: dict[str, str] = {}
    for name, value in (headers or {}).items():
        normalized = str(name).strip()
        if normalized.lower() in BLOCKED_HEADERS or not normalized or "\n" in str(value) or "\r" in str(value):
            raise ValueError(f"Unsafe HTTP header: {name}")
        cleaned[normalized] = str(value)
    return method, url, cleaned


def rest_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    json_body: Any = None,
    timeout: int = 15,
    max_chars: int = 100_000,
) -> dict[str, Any]:
    method, current, headers = validate_rest_request(method, url, headers)
    timeout = max(1, min(timeout, 60))
    max_chars = max(100, min(max_chars, 500_000))
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "AIOS-MCP/1.0", **headers}) as client:
        for redirect_count in range(6):
            response = client.request(method, current, params=query if redirect_count == 0 else None, json=json_body)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect has no location")
                current = validate_public_url(urljoin(current, location))
                hosts = _allowed_hosts()
                if hosts and (urlparse(current).hostname or "").lower() not in hosts:
                    raise PermissionError("Redirect host is not in AIOS_MCP_REST_HOSTS")
                continue
            content_type = response.headers.get("content-type", "")
            text = response.text[:max_chars]
            parsed: Any = None
            if "json" in content_type.lower():
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
            return {
                "url": str(response.url), "status": response.status_code, "ok": response.is_success,
                "content_type": content_type, "headers": dict(response.headers),
                "body": text, "json": parsed, "truncated": len(response.text) > max_chars,
            }
    raise ValueError("Too many redirects")
