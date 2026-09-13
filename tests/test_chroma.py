import pytest
from app.vector_store import ChromaVectorStore, create_vector_store


def record(identity="one", artifact="a", source="document", user="u"):
    return {"id": identity, "artifact_id": artifact, "source_type": source, "user_id": user,
            "text": "Document text", "metadata": {"nested": [1, None]}, "embedding": [1.0, 0.0, 0.0]}


def test_persistence_metadata_and_artifact_replacement(tmp_path):
    store = ChromaVectorStore(tmp_path, "test_vectors", 3)
    store.upsert([record(), record("other", "b", user="v")])
    reopened = ChromaVectorStore(tmp_path, "test_vectors", 3)
    assert sorted(reopened.load(), key=lambda r:r["id"]) == sorted([record(), record("other", "b", user="v")], key=lambda r:r["id"])
    store.upsert([record("replacement")])
    assert {r["id"] for r in store.load()} == {"replacement", "other"}


def test_replace_source_clear_and_validation_before_delete(tmp_path):
    store = ChromaVectorStore(tmp_path, "test_vectors", 3)
    store.upsert([record(), record("memory", "", "memory")])
    invalid = record("bad"); invalid["embedding"] = [1.0]
    with pytest.raises(ValueError): store.replace_all([invalid])
    assert len(store.load()) == 2
    store.replace_source("document", [])
    assert [r["id"] for r in store.load()] == ["memory"]
    store.replace_all([])
    assert store.load() == []


def test_factory_chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("AIOS_CHROMA_PATH", str(tmp_path))
    monkeypatch.setenv("CHROMA_HOST", "")
    assert isinstance(create_vector_store(tmp_path / "old.json", "local-hash-v1", 3), ChromaVectorStore)


def test_pagination(tmp_path):
    store = ChromaVectorStore(tmp_path, "test_vectors", 3)
    store.upsert([record(str(i), "") for i in range(270)])
    assert len(store.load()) == 270


def test_hybrid_retrieval_preserves_tenant_filter(tmp_path, monkeypatch):
    from app import main
    store = ChromaVectorStore(tmp_path, "test_vectors", main.EMBEDDING_DIMENSIONS)
    monkeypatch.setattr(main, "VECTOR_STORE", store)
    mine = record("mine", "a", user="alice")
    foreign = record("foreign", "b", user="bob")
    for item in (mine, foreign):
        item["text"] = "Photosynthesis converts light into chemical energy"
        item["embedding"] = main.generate_embedding(item["text"])
    store.upsert([mine, foreign])
    results = main.hybrid_retrieve("photosynthesis", user_id="alice")
    assert [r["id"] for r in results] == ["mine"]
    assert results[0]["metadata"] == {"nested": [1, None]}


def test_http_server_round_trip(tmp_path):
    """Opt-in verification against a running Chroma server, using a private collection."""
    import os
    import uuid
    host = os.getenv("CHROMA_TEST_HOST")
    if not host:
        pytest.skip("Set CHROMA_TEST_HOST for the Chroma HTTP integration test")
    name = "test_" + uuid.uuid4().hex
    port = int(os.getenv("CHROMA_TEST_PORT", "8000"))
    store = ChromaVectorStore(tmp_path, name, 3, host, port)
    try:
        store.upsert([record()])
        reopened = ChromaVectorStore(tmp_path, name, 3, host, port)
        assert reopened.load() == [record()]
        result = reopened.collection.query(query_embeddings=[[1.0, 0.0, 0.0]], n_results=1)
        assert result["ids"] == [["one"]]
    finally:
        store.client.delete_collection(name)
