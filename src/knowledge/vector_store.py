"""Qdrant vector store, with explicitly selected in-memory demo backend."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

from src.models.embedding_model import EmbeddingModel

logger = logging.getLogger(__name__)


class VectorStore:
    """Index stable document IDs and return scored source documents."""

    def __init__(
        self, embedding_model: EmbeddingModel | None = None,
        backend: str = "memory", client: Any = None,
        collection_name: str | None = None,
    ) -> None:
        self.embedding_model = embedding_model or EmbeddingModel()
        self.backend = backend
        self.collection_name = collection_name or os.getenv("QDRANT_COLLECTION", "beauty_knowledge")
        self.documents: dict[str, dict] = {}
        self.vectors: dict[str, list[float]] = {}
        self.client = client
        if backend == "qdrant" and client is None:
            from qdrant_client import QdrantClient

            self.client = QdrantClient(
                host=os.getenv("QDRANT_HOST", "localhost"),
                port=int(os.getenv("QDRANT_PORT", "6333")), timeout=5,
            )
        elif backend != "memory" and backend != "qdrant":
            raise ValueError(f"Unknown vector backend: {backend}")

    def _retry(self, operation: Any) -> Any:
        for attempt in range(3):
            try:
                return operation()
            except Exception:
                if attempt == 2:
                    logger.exception("Vector store operation failed")
                    raise
                time.sleep(0.2 * (2 ** attempt))

    def create_collection(self) -> None:
        """Create collection if absent without destroying an existing index."""
        if self.backend == "memory":
            return
        from qdrant_client.models import Distance, VectorParams

        def create() -> None:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    self.collection_name,
                    vectors_config=VectorParams(size=self.embedding_model.dimension, distance=Distance.COSINE),
                )
        self._retry(create)

    def add_documents(self, documents: list[dict], batch_size: int = 32) -> int:
        """Upsert documents in bounded batches; IDs remain stable across runs."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.create_collection()
        for start in range(0, len(documents), batch_size):
            batch = documents[start:start + batch_size]
            vectors = self.embedding_model.embed_batch(
                [f"{doc.get('title', '')} {doc.get('content', '')}" for doc in batch]
            )
            records = []
            for doc, vector in zip(batch, vectors):
                item = dict(doc)
                item["id"] = str(item.get("id") or uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{item.get('source', '')}:{item.get('title', '')}:{item.get('content', '')}",
                ))
                records.append((item, vector))
            if self.backend == "memory":
                for item, vector in records:
                    self.documents[item["id"]] = item
                    self.vectors[item["id"]] = vector
            else:
                from qdrant_client.models import PointStruct

                self._retry(lambda: self.client.upsert(
                    collection_name=self.collection_name,
                    points=[PointStruct(id=item["id"], vector=vector, payload=item)
                            for item, vector in records], wait=True,
                ))
        return len(documents)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return source documents with cosine similarity in `score`."""
        if top_k < 1:
            return []
        vector = self.embedding_model.embed(query)
        if self.backend == "memory":
            results = [
                {**doc, "score": sum(a * b for a, b in zip(vector, self.vectors[id_]))}
                for id_, doc in self.documents.items()
            ]
            return sorted(results, key=lambda doc: doc["score"], reverse=True)[:top_k]
        points = self._retry(lambda: self.client.query_points(
            collection_name=self.collection_name, query=vector,
            limit=top_k, with_payload=True,
        ).points)
        return [{**point.payload, "score": point.score} for point in points]
