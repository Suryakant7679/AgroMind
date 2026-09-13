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


class ChromaVectorStore:
    """Preserve complete RAG records while storing supplied vectors in Chroma."""

    def __init__(self, path: Path, collection: str, dimensions: int, host: str = "", port: int = 8000) -> None:
        import chromadb
        self.dimensions = dimensions
        self.client = chromadb.HttpClient(host=host, port=port) if host else chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection, embedding_function=None,
            metadata={"hnsw:space": "cosine", "dimensions": dimensions},
        )
        if (self.collection.metadata or {}).get("dimensions", dimensions) != dimensions:
            raise ValueError("Chroma collection embedding dimensions do not match configuration")

    def load(self) -> list[dict[str, Any]]:
        records = []
        offset = 0
        while True:
            page = self.collection.get(limit=256, offset=offset, include=["metadatas", "embeddings"])
            for index, metadata in enumerate(page["metadatas"]):
                record = json.loads(metadata["record_json"])
                record["embedding"] = [float(value) for value in page["embeddings"][index]]
                records.append(record)
            if len(page["ids"]) < 256:
                return records
            offset += len(page["ids"])

    def _validate(self, records: list[dict[str, Any]]) -> None:
        import math
        ids = [str(record["id"]) for record in records]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate vector record IDs")
        for record in records:
            vector = record.get("embedding", [])
            if len(vector) != self.dimensions or not all(math.isfinite(float(value)) for value in vector):
                raise ValueError("Invalid embedding dimensions or non-finite values")
            json.dumps({key: value for key, value in record.items() if key != "embedding"}, allow_nan=False)

    def _write(self, records: list[dict[str, Any]]) -> None:
        for start in range(0, len(records), 128):
            batch = records[start:start + 128]
            metadata = []
            for record in batch:
                payload = {key: value for key, value in record.items() if key != "embedding"}
                metadata.append({
                    "record_json": json.dumps(payload),
                    "source_type": str(record.get("source_type") or "document"),
                    "artifact_id": str(record.get("artifact_id") or ""),
                    "user_id": str(record.get("user_id") or ""),
                })
            self.collection.upsert(ids=[str(r["id"]) for r in batch],
                                   embeddings=[r["embedding"] for r in batch], metadatas=metadata)

    def upsert(self, records: list[dict[str, Any]]) -> None:
        self._validate(records)
        for artifact_id in {str(r["artifact_id"]) for r in records if r.get("artifact_id")}:
            self.collection.delete(where={"artifact_id": artifact_id})
        self._write(records)

    def replace_source(self, source_type: str, records: list[dict[str, Any]]) -> None:
        self._validate(records)
        self.collection.delete(where={"source_type": source_type})
        self.upsert(records)

    def replace_all(self, records: list[dict[str, Any]]) -> None:
        self._validate(records)
        while True:
            ids = self.collection.get(limit=256, include=[])["ids"]
            if not ids:
                break
            self.collection.delete(ids=ids)
        self._write(records)


def create_chroma_store(dimensions: int) -> ChromaVectorStore:
    root = Path(__file__).resolve().parents[1]
    path = root / os.getenv("AIOS_CHROMA_PATH", "data/chroma")
    return ChromaVectorStore(path, os.getenv("CHROMA_COLLECTION", "aios_embeddings"), dimensions,
                             os.getenv("CHROMA_HOST", ""), int(os.getenv("CHROMA_PORT", "8000")))


def create_vector_store(path: Path, model: str, dimensions: int):
    backend = os.getenv("AIOS_VECTOR_BACKEND", "auto").strip().lower()
    if backend in {"chroma", "chromadb"}:
        return create_chroma_store(dimensions)
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
