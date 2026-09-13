from __future__ import annotations

import os
from pathlib import Path

from app.config import load_env


CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sql", ".html", ".css", ".sh", ".yaml", ".yml"}
EXCLUDED_PARTS = {".git", ".venv", "venv", "node_modules", "data", "dist", "build", "__pycache__"}


def main() -> None:
    load_env()
    from app.main import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, chunk_document_text, generate_embedding, utc_now
    from app.vector_store import QdrantVectorStore

    root = Path(os.getenv("AIOS_CODE_ROOT", Path(__file__).resolve().parents[1])).resolve()
    records = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in CODE_EXTENSIONS or EXCLUDED_PARTS.intersection(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for chunk in chunk_document_text(text, chunk_size=1600, overlap=200):
            chunk_id = str(chunk["id"])
            records.append({
                "id": f"code:{relative}:{chunk_id}", "source_type": "code", "source_id": relative,
                "chunk_id": chunk_id, "chunk_index": chunk["index"], "filename": relative,
                "document_type": path.suffix.lower().lstrip("."), "text": chunk["text"],
                "embedding": generate_embedding(chunk["text"]), "embedding_model": EMBEDDING_MODEL,
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "metadata": {"source_path": str(path), "start_char": chunk["start_char"], "end_char": chunk["end_char"]},
                "created_at": utc_now(),
            })
    store = QdrantVectorStore(os.environ["QDRANT_URL"], os.getenv("QDRANT_COLLECTION", "aios_embeddings"), EMBEDDING_DIMENSIONS, os.getenv("QDRANT_API_KEY", ""))
    store.replace_source("code", records)
    print(f"Indexed {len(records)} code chunk(s) from {root}.")


if __name__ == "__main__": main()
