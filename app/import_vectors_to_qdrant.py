from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import load_env
from app.vector_store import QdrantVectorStore


def main() -> None:
    load_env()
    root = Path(__file__).resolve().parents[1]
    source = root / os.getenv("AIOS_VECTOR_INDEX", "data/vectors.json")
    payload = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {"records": []}
    dimensions = int(os.getenv("AIOS_EMBEDDING_DIMENSIONS", "64"))
    records = [record for record in payload.get("records", []) if len(record.get("embedding", [])) == dimensions]
    for record in records:
        record.setdefault("source_type", "document")
    store = QdrantVectorStore(os.environ["QDRANT_URL"], os.getenv("QDRANT_COLLECTION", "aios_embeddings"), dimensions, os.getenv("QDRANT_API_KEY", ""))
    store.upsert(records)
    print(f"Imported {len(records)} vector record(s) into Qdrant.")


if __name__ == "__main__": main()
