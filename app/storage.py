from __future__ import annotations

import os

from app.postgres_store import PostgreSQLConversationStore
from app.store import ConversationStore


def create_store() -> ConversationStore:
    backend = os.getenv("AIOS_STORAGE_BACKEND", "auto").strip().lower()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if backend not in {"auto", "json", "postgres"}:
        raise ValueError(f"Unknown AIOS_STORAGE_BACKEND: {backend}")
    if backend == "postgres" or (backend == "auto" and database_url):
        if not database_url:
            raise RuntimeError("DATABASE_URL is required when AIOS_STORAGE_BACKEND=postgres")
        return PostgreSQLConversationStore(
            database_url,
            os.getenv("AIOS_MEMORY_FILE", "data/memory.json"),
        )
    return ConversationStore(os.getenv("AIOS_DATA_FILE", "data/conversations.json"))

