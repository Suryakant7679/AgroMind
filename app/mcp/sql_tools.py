from __future__ import annotations

import re


READ_ONLY_SQL = re.compile(r"^\s*(select|with|explain|show|pragma)\b", re.I | re.S)
FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|attach|detach|replace)\b", re.I)


def validate_read_only_sql(query: str, allow_pragma: bool = False) -> str:
    cleaned = query.strip().rstrip(";").strip()
    if not cleaned or ";" in cleaned: raise ValueError("Exactly one SQL statement is allowed")
    if not READ_ONLY_SQL.match(cleaned) or FORBIDDEN_SQL.search(cleaned): raise PermissionError("Only read-only SQL is allowed")
    if cleaned.lower().startswith("pragma") and not allow_pragma: raise PermissionError("PRAGMA is not allowed for this database")
    return cleaned
