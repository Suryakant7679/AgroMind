from __future__ import annotations

import os
import re
from typing import Any

import httpx


class GitHubReader:
    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN", "")

    def _get(self, owner: str, repo: str, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo): raise ValueError("Invalid repository name")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "AIOS-MCP/1.0"}
        if self.token: headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.get(f"https://api.github.com/repos/{owner}/{repo}{endpoint}", headers=headers, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def repository(self, owner: str, repo: str) -> dict[str, Any]:
        data = self._get(owner, repo, "")
        return {key: data.get(key) for key in ("full_name", "description", "private", "default_branch", "html_url", "stargazers_count", "forks_count", "open_issues_count", "updated_at")}
    def issues(self, owner: str, repo: str, state: str = "open", limit: int = 20) -> list[dict[str, Any]]:
        values = self._get(owner, repo, "/issues", {"state": state, "per_page": max(1, min(limit, 100))})
        return [{"number": item["number"], "title": item["title"], "state": item["state"], "url": item["html_url"]} for item in values if "pull_request" not in item]
    def contributors(self, owner: str, repo: str, limit: int = 100) -> list[dict[str, Any]]:
        values = self._get(owner, repo, "/contributors", {"per_page": max(1, min(limit, 100))})
        return [
            {"login": item["login"], "contributions": item.get("contributions", 0), "url": item["html_url"]}
            for item in values
        ]

    def pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        limit: int = 20,
        sort: str = "updated",
        direction: str = "desc",
    ) -> list[dict[str, Any]]:
        if state not in {"open", "closed", "all"}:
            raise ValueError("Pull-request state must be open, closed, or all")
        if sort not in {"created", "updated", "popularity", "long-running"}:
            raise ValueError("Invalid pull-request sort")
        if direction not in {"asc", "desc"}:
            raise ValueError("Pull-request direction must be asc or desc")
        values = self._get(
            owner,
            repo,
            "/pulls",
            {"state": state, "sort": sort, "direction": direction, "per_page": max(1, min(limit, 100))},
        )
        return [
            {
                "number": item["number"],
                "title": item["title"],
                "state": item["state"],
                "url": item["html_url"],
                "draft": item.get("draft", False),
                "author": (item.get("user") or {}).get("login"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "closed_at": item.get("closed_at"),
                "merged_at": item.get("merged_at"),
            }
            for item in values
        ]
