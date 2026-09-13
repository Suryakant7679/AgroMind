"""Copy existing JSON or Qdrant vectors into Chroma without deleting the source."""
import argparse
import json
import os
from pathlib import Path
from app.config import load_env
from app.vector_store import create_chroma_store, QdrantVectorStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["json", "qdrant"], default="json")
    args = parser.parse_args()
    load_env(override=False)
    dimensions = int(os.getenv("AIOS_EMBEDDING_DIMENSIONS", "64"))
    if args.source == "qdrant":
        from qdrant_client import QdrantClient
        # Read the source without creating collections or changing indexes.
        source = QdrantVectorStore.__new__(QdrantVectorStore)
        source.client = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.getenv("QDRANT_API_KEY") or None, timeout=30)
        source.collection = os.getenv("QDRANT_COLLECTION", "aios_embeddings")
        records = source.load()
    else:
        path = Path(__file__).resolve().parents[1] / os.getenv("AIOS_VECTOR_INDEX", "data/vectors.json")
        records = json.loads(path.read_text(encoding="utf-8"))["records"]
    store = create_chroma_store(dimensions)
    store.upsert(records)
    actual = {record["id"]: record for record in store.load()}
    for record in records:
        saved = actual[record["id"]]
        assert {k: v for k, v in saved.items() if k != "embedding"} == {k: v for k, v in record.items() if k != "embedding"}
        assert all(abs(a-b) < 1e-5 for a, b in zip(saved["embedding"], record["embedding"]))
    print(f"Copied and verified {len(records)} vector records in Chroma. Source preserved.")


if __name__ == "__main__":
    main()
