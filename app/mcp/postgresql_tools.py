from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.mcp.sql_tools import validate_read_only_sql


class PostgreSQLReader:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("DATABASE_URL", "")
        if not self.url: raise RuntimeError("DATABASE_URL is required")

    def query(self, sql: str, parameters: list[Any] | None = None, limit: int = 200) -> dict[str, Any]:
        statement = validate_read_only_sql(sql)
        limit = max(1, min(limit, 1000))
        with psycopg.connect(self.url, options="-c default_transaction_read_only=on -c statement_timeout=10000") as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(statement, parameters or [])
                rows = cursor.fetchmany(limit + 1) if cursor.description else []
        return {"rows": rows[:limit], "row_count": min(len(rows), limit), "truncated": len(rows) > limit}

    def tables(self) -> list[dict[str, Any]]:
        return self.query("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY table_schema, table_name", limit=1000)["rows"]

    def columns(self, table: str, schema: str = "public") -> list[dict[str, Any]]:
        return self.query("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", [schema, table], 500)["rows"]
