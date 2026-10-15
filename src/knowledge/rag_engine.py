"""Hybrid retrieval with Chinese tokenization and reciprocal rank fusion."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from src.knowledge.vector_store import VectorStore

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "beauty_knowledge"


def tokenize(text: str) -> list[str]:
    """Use Chinese characters and bigrams plus Latin words for lexical matching."""
    chinese = re.findall(r"[\u4e00-\u9fff]+", text.lower())
    return (
        [ch for part in chinese for ch in part]
        + [part[i:i + 2] for part in chinese for i in range(len(part) - 1)]
        + re.findall(r"[a-z0-9-]+", text.lower())
    )


def load_documents(directory: Path = DATA_DIR) -> list[dict]:
    """Load knowledge documents; empathy templates are not factual evidence."""
    documents = []
    for path in sorted(directory.glob("*.json")):
        if path.name == "empathy_templates.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("content"):
                    document = dict(item)
                    document["id"] = str(document.get("id") or uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{document.get('source', '')}:{document.get('title', '')}:{document.get('content', '')}",
                    ))
                    documents.append(document)
    return documents


class RAGEngine:
    """Fuse local BM25 and vector retrieval while retaining provenance."""

    def __init__(
        self, vector_store: VectorStore | None = None, documents: list[dict] | None = None,
        reranker: object | None = None,
    ) -> None:
        from rank_bm25 import BM25Okapi

        import os

        self.vector_store = vector_store or VectorStore(
            backend=os.getenv("VECTOR_BACKEND", "memory"))
        self.documents = documents if documents is not None else load_documents()
        self.reranker = reranker
        self.tokens = [tokenize(f"{d.get('title', '')} {d.get('content', '')} {' '.join(d.get('tags', []))}")
                       for d in self.documents]
        self.bm25 = BM25Okapi(self.tokens) if self.tokens else None
        if self.vector_store.backend == "memory":
            self.vector_store.add_documents(self.documents)

    def bm25_search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return ranked documents with lexical scores."""
        if self.bm25 is None or not tokenize(query):
            return []
        scores = self.bm25.get_scores(tokenize(query))
        indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [{**self.documents[i], "score": float(scores[i])} for i in indices[:top_k] if scores[i] > 0]

    @staticmethod
    def reciprocal_rank_fusion(*rankings: list[dict], k: int = 60) -> list[dict]:
        """Merge ranked lists by stable ID, preserving strongest similarity."""
        merged: dict[str, dict] = {}
        for ranking in rankings:
            for rank, doc in enumerate(ranking, 1):
                key = str(doc.get("id") or f"{doc.get('source')}:{doc.get('title')}:{doc.get('content')}")
                entry = merged.setdefault(key, {**doc, "rrf_score": 0.0, "vector_score": 0.0})
                entry["rrf_score"] += 1 / (k + rank)
                if ranking is rankings[0]:
                    entry["vector_score"] = float(doc.get("score", 0))
        return sorted(merged.values(), key=lambda doc: doc["rrf_score"], reverse=True)

    def hybrid_search(self, query: str, top_k: int = 5) -> list[dict]:
        """Retrieve and fuse top candidates from both rankers."""
        if not query.strip() or top_k < 1:
            return []
        vector = self.vector_store.search(query, top_k * 2)
        lexical = self.bm25_search(query, top_k * 2)
        fused = self.reciprocal_rank_fusion(vector, lexical)
        if self.reranker is not None:
            ranked = self.reranker.rerank(query, fused)
            if len(ranked) != len(fused) or {doc["id"] for doc in ranked} != {doc["id"] for doc in fused}:
                raise ValueError("Reranker must retain exactly the retrieved document IDs.")
            originals = {doc["id"]: doc for doc in fused}
            if any(any(doc.get(key) != value for key, value in originals[doc["id"]].items())
                   for doc in ranked):
                raise ValueError("Reranker must not change knowledge content or approval.")
            fused = ranked
        return fused[:top_k]
