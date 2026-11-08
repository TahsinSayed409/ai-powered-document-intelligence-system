import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import SearchIndex
from app.services.embeddings import EmbeddingError, cosine_similarity, embed_texts


def keyword_search(documents: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    query_terms = {term.casefold() for term in re.findall(r"[A-Za-z0-9]+", query)}
    if not query_terms:
        return []

    matches = []
    for document in documents:
        extracted = document.get("extracted_data") or {}
        haystack = " ".join(
            str(value or "")
            for value in [
                document.get("filename"),
                document.get("invoice_number"),
                document.get("supplier_name"),
                document.get("customer_name"),
                document.get("currency"),
                document.get("total"),
                document.get("raw_text"),
                extracted.get("raw_text"),
            ]
        ).casefold()
        score = sum(1 for term in query_terms if term in haystack)
        if score:
            matches.append({**document, "search_score": score})
    return sorted(matches, key=lambda item: item["search_score"], reverse=True)


def semantic_search(
    documents: list[dict[str, Any]],
    query: str,
    db: Session,
) -> list[dict[str, Any]]:
    document_ids = [document["id"] for document in documents]
    if not query.strip() or not document_ids:
        return []
    indexes = db.query(SearchIndex).filter(
        SearchIndex.document_id.in_(document_ids),
        SearchIndex.embedding.isnot(None),
    ).all()
    if not indexes:
        return []

    indexed_document_ids = {index.document_id for index in indexes}
    for document in documents:
        if document["id"] not in indexed_document_ids:
            continue
        metadata = document.get("extracted_data") or {}
        if (
            metadata.get("embedding_model") != settings.embedding_model_name
            or metadata.get("embedding_dimension") != settings.embedding_dimension
        ):
            raise EmbeddingError(
                f"Document {document['id']} embeddings are missing or use a "
                "different model/dimension. Run "
                "'python scripts/reindex_embeddings.py' from backend\\."
            )

    query_vector = embed_texts([query])[0]
    best_scores: dict[int, float] = {}
    for index in indexes:
        vector = index.embedding
        if not isinstance(vector, list):
            continue
        if len(vector) != settings.embedding_dimension:
            raise EmbeddingError(
                f"Document {index.document_id} contains an embedding with an "
                "unexpected dimension. Run "
                "'python scripts/reindex_embeddings.py' from backend\\."
            )
        score = cosine_similarity(query_vector, vector)
        previous = best_scores.get(index.document_id, float("-inf"))
        if score > previous:
            best_scores[index.document_id] = score

    document_by_id = {document["id"]: document for document in documents}
    ranked = [
        {
            **document_by_id[document_id],
            "search_score": round(score, 6),
        }
        for document_id, score in best_scores.items()
        if document_id in document_by_id
    ]
    return sorted(ranked, key=lambda item: item["search_score"], reverse=True)
