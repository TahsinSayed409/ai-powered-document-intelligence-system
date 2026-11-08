import pytest

from app.config import settings
from app.services.embeddings import (
    EMBEDDING_CHUNK_CHARS,
    EmbeddingError,
    chunk_text,
    embed_document_text,
    embed_texts,
)


class _Array:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class _FakeEmbeddingModel:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return _Array(self.vectors)


def test_local_embedding_model_receives_cpu_input_and_returns_vectors(monkeypatch):
    model = _FakeEmbeddingModel([[0.1] * 384, [0.2] * 384])
    monkeypatch.setattr("app.services.embeddings._get_embedding_model", lambda: model)

    vectors = embed_texts(["first document", "second document"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 384
    assert model.calls[0][1]["device"] == "cpu"
    assert model.calls[0][1]["normalize_embeddings"] is False


def test_empty_embedding_input_does_not_load_model(monkeypatch):
    def unexpected_model_load():
        raise AssertionError("An empty input must not load the embedding model.")

    monkeypatch.setattr("app.services.embeddings._get_embedding_model", unexpected_model_load)

    assert embed_texts([]) == []
    assert embed_document_text(" \n") == []


def test_local_embedding_dimension_is_validated(monkeypatch):
    monkeypatch.setattr(settings, "embedding_dimension", 2)
    monkeypatch.setattr(
        "app.services.embeddings._get_embedding_model",
        lambda: _FakeEmbeddingModel([[0.1, 0.2, 0.3]]),
    )

    with pytest.raises(EmbeddingError, match="invalid vector or dimension"):
        embed_texts(["invoice"])


def test_document_text_is_chunked_for_local_model():
    text = "a" * (EMBEDDING_CHUNK_CHARS + 1)

    assert chunk_text(text) == ["a" * EMBEDDING_CHUNK_CHARS, "a"]
