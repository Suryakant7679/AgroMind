from __future__ import annotations

import os
from pathlib import Path
from typing import Any


HIDDEN_NAMES = {".env", ".git", "__pycache__", ".pytest_cache"}


def protected_path(parts: tuple[str, ...]) -> bool:
    return any(part.casefold() in HIDDEN_NAMES or part.casefold().startswith(".env.") for part in parts)


class WorkspaceFilesystem:
    def __init__(self, root: str | Path | None = None, allow_write: bool | None = None) -> None:
        default_root = Path(__file__).resolve().parents[2]
        self.root = Path(root or os.getenv("AIOS_MCP_WORKSPACE_ROOT", default_root)).resolve()
        self.allow_write = (
            os.getenv("AIOS_MCP_FILESYSTEM_WRITE", "false").lower() == "true"
            if allow_write is None else allow_write
        )

    def resolve(self, relative_path: str = ".", must_exist: bool = True) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Path escapes the configured workspace root")
        relative_parts = candidate.relative_to(self.root).parts if candidate != self.root else ()
        if protected_path(relative_parts):
            raise ValueError("Access to protected workspace paths is denied")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(relative_path)
        return candidate

    def list_files(self, path: str = ".", recursive: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        target = self.resolve(path)
        if not target.is_dir():
            raise ValueError("Path is not a directory")
        iterator = target.rglob("*") if recursive else target.iterdir()
        results = []
        for item in iterator:
            try:
                relative = item.relative_to(self.root)
                self.resolve(relative.as_posix())
            except (ValueError, OSError):
                continue
            results.append({
                "path": relative.as_posix(), "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
            if len(results) >= max(1, min(limit, 2000)):
                break
        return sorted(results, key=lambda value: value["path"])

    def read_file(self, path: str, max_chars: int = 100_000) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.is_file():
            raise ValueError("Path is not a file")
        max_chars = max(1, min(max_chars, 1_000_000))
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"path": target.relative_to(self.root).as_posix(), "content": content[:max_chars], "truncated": len(content) > max_chars}

    def search_text(self, query: str, path: str = ".", limit: int = 100) -> list[dict[str, Any]]:
        if not query:
            raise ValueError("query is required")
        target = self.resolve(path)
        files = [target] if target.is_file() else target.rglob("*")
        matches = []
        for file in files:
            if not file.is_file():
                continue
            try:
                self.resolve(file.relative_to(self.root).as_posix())
                for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if query.lower() in line.lower():
                        matches.append({"path": file.relative_to(self.root).as_posix(), "line": number, "text": line[:500]})
                        if len(matches) >= max(1, min(limit, 1000)):
                            return matches
            except (OSError, ValueError):
                continue
        return matches

    def write_file(self, path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
        if not self.allow_write:
            raise PermissionError("Filesystem writes are disabled; set AIOS_MCP_FILESYSTEM_WRITE=true to enable")
        target = self.resolve(path, must_exist=False)
        if target.exists() and not overwrite:
            raise FileExistsError("File exists; pass overwrite=true to replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": target.relative_to(self.root).as_posix(), "bytes_written": len(content.encode("utf-8"))}
