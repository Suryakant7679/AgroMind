from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5


class JsonVectorStore:
    def __init__(self, path: Path, model: str, dimensions: int) -> None:
        self.path, self.model, self.dimensions = path, model, dimensions

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists(): return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return payload.get("records", [])

    def replace_all(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"embedding_model": self.model, "embedding_dimensions": self.dimensions, "record_count": len(records), "records": records}, indent=2), encoding="utf-8")

    def upsert(self, records: list[dict[str, Any]]) -> None:
        existing = self.load()
        ids = {item["id"] for item in records}
        artifacts = {item.get("artifact_id") for item in records if item.get("artifact_id")}
        self.replace_all([*records, *[item for item in existing if item.get("id") not in ids and item.get("artifact_id") not in artifacts]])

    def replace_source(self, source_type: str, records: list[dict[str, Any]]) -> None:
        self.replace_all([*records, *[item for item in self.load() if item.get("source_type", "document") != source_type]])


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, dimensions: int, api_key: str = "") -> None:
        from qdrant_client import QdrantClient
        self.client = QdrantClient(url=url, api_key=api_key or None, timeout=5)
        self.collection, self.dimensions = collection, dimensions
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client import models
        if not self.client.collection_exists(self.collection):
            try:
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(size=self.dimensions, distance=models.Distance.COSINE),
                    on_disk_payload=True,
                )
            except Exception:
                # Multiple app/worker processes may race to create the collection.
                # Suppress only the case where another process created it first.
                if not self.client.collection_exists(self.collection):
                    raise
        for field in ("source_type", "artifact_id", "source_id"):
            try:
                self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
            except Exception:
                pass

    def load(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = None
        while True:
            points, offset = self.client.scroll(self.collection, limit=256, offset=offset, with_payload=True, with_vectors=True)
            for point in points:
                record = dict(point.payload or {})
                record["embedding"] = list(point.vector or [])
                records.append(record)
            if offset is None: break
        return records

    def replace_all(self, records: list[dict[str, Any]]) -> None:
        from qdrant_client import models
        self.client.delete(self.collection, models.FilterSelector(filter=models.Filter(must=[])), wait=True)
        self.upsert(records)

    def upsert(self, records: list[dict[str, Any]]) -> None:
        from qdrant_client import models
        if not records: return
        artifact_ids = {str(item.get("artifact_id")) for item in records if item.get("artifact_id")}
        for artifact_id in artifact_ids:
            self._delete_filter("artifact_id", artifact_id)
        points = []
        for record in records:
            payload = {key: value for key, value in record.items() if key != "embedding"}
            payload.setdefault("source_type", "document")
            points.append(models.PointStruct(id=str(uuid5(NAMESPACE_URL, str(record["id"]))), vector=record["embedding"], payload=payload))
        for start in range(0, len(points), 128):
            self.client.upsert(self.collection, points=points[start:start + 128], wait=True)

    def replace_source(self, source_type: str, records: list[dict[str, Any]]) -> None:
        self._delete_filter("source_type", source_type)
        self.upsert(records)

    def _delete_filter(self, field: str, value: str) -> None:
        from qdrant_client import models
        self.client.delete(
            self.collection,
            models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key=field, match=models.MatchValue(value=value))])),
            wait=True,
        )


def create_vector_store(path: Path, model: str, dimensions: int):
    backend = os.getenv("AIOS_VECTOR_BACKEND", "auto").strip().lower()
    url = os.getenv("QDRANT_URL", "").strip()
    if backend == "json" or (backend == "auto" and not url):
        return JsonVectorStore(path, model, dimensions)
    if backend not in {"auto", "qdrant"}: raise ValueError(f"Unknown AIOS_VECTOR_BACKEND: {backend}")
    if not url: raise RuntimeError("QDRANT_URL is required for Qdrant vector storage")
    try:
        return QdrantVectorStore(url, os.getenv("QDRANT_COLLECTION", "aios_embeddings"), dimensions, os.getenv("QDRANT_API_KEY", ""))
    except Exception:
        if backend == "qdrant": raise
        return JsonVectorStore(path, model, dimensions)
