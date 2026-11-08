from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

from app.config import settings

EMBEDDING_BATCH_SIZE = 16
EMBEDDING_CHUNK_CHARS = 1000


class EmbeddingError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_embedding_model(model_name: str, cache_dir: str, dimension: int):
    os.environ.setdefault("HF_HOME", cache_dir)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingError(
            "Local semantic search requires sentence-transformers. Install "
            "backend\\requirements.txt in the active backend environment."
        ) from exc

    model = SentenceTransformer(model_name, cache_folder=cache_dir, device="cpu")
    actual_dimension = model.get_embedding_dimension()
    if actual_dimension != dimension:
        raise EmbeddingError(
            f"Embedding model '{model_name}' returns {actual_dimension} dimensions; "
            f"configured EMBEDDING_DIMENSION is {dimension}."
        )
    return model


def _get_embedding_model():
    return _load_embedding_model(
        settings.embedding_model_name,
        settings.model_cache_dir,
        settings.embedding_dimension,
    )


def chunk_text(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    return [
        cleaned[start : start + EMBEDDING_CHUNK_CHARS]
        for start in range(0, len(cleaned), EMBEDDING_CHUNK_CHARS)
    ]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_embedding_model()
    vectors = model.encode(
        texts,
        batch_size=EMBEDDING_BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=False,
        device="cpu",
    )
    normalized_vectors: list[list[float]] = []
    for vector in vectors.tolist():
        if len(vector) != settings.embedding_dimension or not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingError(
                "The local embedding model returned an invalid vector or dimension."
            )
        normalized_vectors.append([float(value) for value in vector])
    if len(normalized_vectors) != len(texts):
        raise EmbeddingError("The local embedding model returned an incomplete batch.")
    return normalized_vectors


def embed_document_text(text: str) -> list[tuple[str, list[float]]]:
    chunks = chunk_text(text)
    if not chunks:
        return []
    return list(zip(chunks, embed_texts(chunks)))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
