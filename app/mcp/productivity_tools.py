from __future__ import annotations

import os
from typing import Any

import httpx


class ProductivityReader:
    """Read-only Slack and Notion access using narrowly scoped API calls."""

    def __init__(self, slack_token: str | None = None, notion_token: str | None = None) -> None:
        self.slack_token = slack_token if slack_token is not None else os.getenv("SLACK_BOT_TOKEN", "")
        self.notion_token = notion_token if notion_token is not None else os.getenv("NOTION_TOKEN", "")

    def _slack(self, endpoint: str, params: dict[str, Any]) -> Any:
        if not self.slack_token:
            raise RuntimeError("SLACK_BOT_TOKEN is not configured")
        response = httpx.get(
            f"https://slack.com/api/{endpoint}",
            headers={"Authorization": f"Bearer {self.slack_token}"}, params=params, timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown_error')}")
        return data

    def slack_channels(self, limit: int = 100) -> list[dict[str, Any]]:
        data = self._slack("conversations.list", {"limit": max(1, min(limit, 200)), "exclude_archived": "true"})
        return [{key: channel.get(key) for key in ("id", "name", "is_private", "topic", "purpose")} for channel in data.get("channels", [])]

    def slack_history(self, channel: str, limit: int = 50) -> list[dict[str, Any]]:
        if not channel or len(channel) > 32 or not channel.isalnum():
            raise ValueError("Invalid Slack channel ID")
        data = self._slack("conversations.history", {"channel": channel, "limit": max(1, min(limit, 100))})
        return [{key: message.get(key) for key in ("ts", "user", "text", "thread_ts")} for message in data.get("messages", [])]

    def _notion(self, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.notion_token:
            raise RuntimeError("NOTION_TOKEN is not configured")
        headers = {"Authorization": f"Bearer {self.notion_token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
        if payload is None:
            response = httpx.get(f"https://api.notion.com/v1/{endpoint}", headers=headers, timeout=15)
        else:
            response = httpx.post(f"https://api.notion.com/v1/{endpoint}", headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()

    def notion_search(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"page_size": max(1, min(limit, 100))}
        if query.strip():
            payload["query"] = query.strip()[:200]
        data = self._notion("search", payload)
        return [{key: item.get(key) for key in ("id", "object", "url", "last_edited_time", "properties")} for item in data.get("results", [])]

    def notion_page(self, page_id: str) -> dict[str, Any]:
        normalized = page_id.replace("-", "")
        if len(normalized) != 32 or any(char not in "0123456789abcdefABCDEF" for char in normalized):
            raise ValueError("Invalid Notion page ID")
        return self._notion(f"pages/{page_id}")
