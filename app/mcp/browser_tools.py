from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) URLs without embedded credentials are allowed")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local and private network URLs are blocked")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Local and private network URLs are blocked")
    return url


def fetch_url(url: str, max_chars: int = 50_000) -> dict[str, Any]:
    current = validate_public_url(url)
    max_chars = max(100, min(max_chars, 200_000))
    with httpx.Client(timeout=10, follow_redirects=False, headers={"User-Agent": "AIOS-MCP/1.0"}) as client:
        for _ in range(5):
            response = client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location: raise ValueError("Redirect has no location")
                current = validate_public_url(urljoin(current, location))
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not any(value in content_type.lower() for value in ("text/", "json", "xml")):
                raise ValueError(f"Unsupported response content type: {content_type}")
            text = response.text
            return {"url": str(response.url), "status": response.status_code, "content_type": content_type, "content": text[:max_chars], "truncated": len(text) > max_chars}
    raise ValueError("Too many redirects")


def extract_links(url: str, limit: int = 100) -> list[dict[str, str]]:
    page = fetch_url(url, max_chars=200_000)
    links = []
    for href, label in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page["content"], re.I | re.S):
        absolute = urljoin(page["url"], unescape(href))
        if urlparse(absolute).scheme not in {"http", "https"}: continue
        text = re.sub(r"<[^>]+>", " ", unescape(label))
        links.append({"url": absolute, "text": " ".join(text.split())[:300]})
        if len(links) >= max(1, min(limit, 500)): break
    return links
