from __future__ import annotations

import os

from app.config import load_env
from app.postgres_store import PostgreSQLConversationStore
from app.store import ConversationStore


def main() -> None:
    load_env()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing")
    source = ConversationStore(os.getenv("AIOS_DATA_FILE", "data/conversations.json"))
    payload = source._load()
    target = PostgreSQLConversationStore(database_url, os.getenv("AIOS_MEMORY_FILE", "data/memory.json"))
    target._save(payload)
    print(
        f"Imported {len(payload['sessions'])} session(s) and "
        f"{len(payload['conversations'])} chat(s) into PostgreSQL."
    )


if __name__ == "__main__":
    main()
