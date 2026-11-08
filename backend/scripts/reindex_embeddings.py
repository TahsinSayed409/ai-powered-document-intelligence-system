from app.config import settings
from app.db import SessionLocal
from app.models import Document, SearchIndex
from app.services.embeddings import chunk_text, embed_texts


def reindex_embeddings() -> int:
    db = SessionLocal()
    reindexed_documents = 0
    try:
        documents = (
            db.query(Document)
            .join(SearchIndex, SearchIndex.document_id == Document.id)
            .distinct()
            .order_by(Document.id)
            .all()
        )
        for document in documents:
            indexes = (
                db.query(SearchIndex)
                .filter(SearchIndex.document_id == document.id)
                .order_by(SearchIndex.id)
                .all()
            )
            chunks = [
                chunk
                for index in indexes
                for chunk in chunk_text(index.text)
            ]
            vectors = embed_texts(chunks)
            db.query(SearchIndex).filter(
                SearchIndex.document_id == document.id
            ).delete(synchronize_session=False)
            db.add_all(
                SearchIndex(document_id=document.id, text=chunk, embedding=vector)
                for chunk, vector in zip(chunks, vectors)
            )
            extracted_data = dict(document.extracted_data or {})
            extracted_data["embedding_model"] = settings.embedding_model_name
            extracted_data["embedding_dimension"] = settings.embedding_dimension
            document.extracted_data = extracted_data
            db.commit()
            reindexed_documents += 1
    finally:
        db.close()
    return reindexed_documents


if __name__ == "__main__":
    count = reindex_embeddings()
    print(
        f"Reindexed {count} documents with {settings.embedding_model_name} "
        f"({settings.embedding_dimension} dimensions)."
    )
