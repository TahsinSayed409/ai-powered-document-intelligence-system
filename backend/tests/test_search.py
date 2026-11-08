import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.models import Document, SearchIndex
from app.services.embeddings import EmbeddingError
from app.services.search import keyword_search, semantic_search


def test_keyword_search_uses_indexed_document_text():
    documents = [
        {
            "id": 1,
            "filename": "invoice.pdf",
            "raw_text": "The invoice is for a precision microscope",
        },
        {"id": 2, "filename": "receipt.pdf", "raw_text": "Office supplies"},
    ]

    results = keyword_search(documents, "microscope")

    assert [item["id"] for item in results] == [1]


def test_semantic_search_ranks_stored_vectors_by_cosine_similarity(monkeypatch):
    monkeypatch.setattr(settings, "embedding_dimension", 2)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)()
    try:
        first = Document(filename="a.pdf", file_type="pdf", storage_path="a.pdf")
        second = Document(filename="b.pdf", file_type="pdf", storage_path="b.pdf")
        test_session.add_all([first, second])
        test_session.commit()
        test_session.refresh(first)
        test_session.refresh(second)
        test_session.add_all([
            SearchIndex(document_id=first.id, text="semantic match", embedding=[1.0, 0.0]),
            SearchIndex(document_id=second.id, text="unrelated", embedding=[0.0, 1.0]),
        ])
        test_session.commit()

        monkeypatch.setattr(
            "app.services.search.embed_texts",
            lambda texts: [[0.9, 0.1] for _ in texts],
        )

        results = semantic_search(
            [
                {
                    "id": first.id,
                    "filename": first.filename,
                    "extracted_data": {
                        "embedding_model": settings.embedding_model_name,
                        "embedding_dimension": 2,
                    },
                },
                {
                    "id": second.id,
                    "filename": second.filename,
                    "extracted_data": {
                        "embedding_model": settings.embedding_model_name,
                        "embedding_dimension": 2,
                    },
                },
            ],
            "conceptually related query",
            test_session,
        )

        assert results[0]["id"] == first.id
        assert results[0]["search_score"] > results[1]["search_score"]
    finally:
        test_session.close()
        engine.dispose()


def test_semantic_search_rejects_vectors_from_another_embedding_model():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)()
    try:
        document = Document(filename="legacy.pdf", file_type="pdf", storage_path="legacy.pdf")
        test_session.add(document)
        test_session.commit()
        test_session.refresh(document)
        test_session.add(
            SearchIndex(
                document_id=document.id,
                text="legacy vector",
                embedding=[0.1] * settings.embedding_dimension,
            )
        )
        test_session.commit()

        with pytest.raises(EmbeddingError, match="scripts/reindex_embeddings.py"):
            semantic_search(
                [{
                    "id": document.id,
                    "filename": document.filename,
                    "extracted_data": {
                        "embedding_model": "old-embedding-model",
                        "embedding_dimension": settings.embedding_dimension,
                    },
                }],
                "invoice query",
                test_session,
            )
    finally:
        test_session.close()
        engine.dispose()


def test_semantic_search_returns_no_results_for_blank_query():
    assert semantic_search([], "   ", db=None) == []
