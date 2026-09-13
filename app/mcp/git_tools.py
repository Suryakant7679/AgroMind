from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.mcp.process_tools import run_process, workspace_root


class GitInspector:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or workspace_root()).resolve()

    def _git(self, args: list[str], timeout: int = 20) -> dict[str, Any]:
        return run_process(["git", "-C", str(self.root), *args], timeout=timeout)

    def status(self) -> dict[str, Any]: return self._git(["status", "--short", "--branch"])
    def diff(self, staged: bool = False, path: str = "") -> dict[str, Any]:
        args = ["diff"] + (["--cached"] if staged else [])
        if path:
            target = (self.root / path).resolve()
            if self.root not in target.parents and target != self.root: raise ValueError("Path escapes repository")
            args += ["--", target.relative_to(self.root).as_posix()]
        return self._git(args)
    def log(self, limit: int = 20) -> dict[str, Any]: return self._git(["log", f"-{max(1, min(limit, 100))}", "--oneline", "--decorate"])
    def show(self, revision: str = "HEAD") -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_./~^{}@+-]{1,200}", revision) or revision.startswith("-"): raise ValueError("Invalid revision")
        return self._git(["show", "--stat", "--oneline", revision])
    def branches(self) -> dict[str, Any]: return self._git(["branch", "--all", "--verbose", "--no-abbrev"])
