from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.mcp.process_tools import workspace_root
from app.mcp.sql_tools import validate_read_only_sql


class SQLiteReader:
    def __init__(self, path: str | Path | None = None) -> None:
        candidate = Path(path or os.getenv("AIOS_SQLITE_PATH", "data/aios.db"))
        self.path = (candidate if candidate.is_absolute() else workspace_root() / candidate).resolve()
        root = workspace_root()
        if self.path != root and root not in self.path.parents: raise ValueError("SQLite path escapes workspace")

    def _connect(self):
        if not self.path.exists(): raise FileNotFoundError(f"SQLite database not found: {self.path}")
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def query(self, sql: str, parameters: list[Any] | None = None, limit: int = 200) -> dict[str, Any]:
        statement = validate_read_only_sql(sql, allow_pragma=True)
        limit = max(1, min(limit, 1000))
        with closing(self._connect()) as connection:
            rows = connection.execute(statement, parameters or []).fetchmany(limit + 1)
        values = [dict(row) for row in rows]
        return {"rows": values[:limit], "row_count": min(len(values), limit), "truncated": len(values) > limit}

    def tables(self) -> list[dict[str, Any]]:
        return self.query("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name", limit=1000)["rows"]
