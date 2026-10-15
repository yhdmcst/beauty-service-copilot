"""Chinese embeddings with optional BGE model and deterministic offline fallback."""

from __future__ import annotations

import hashlib
import math
import os
import threading
from collections import OrderedDict


class EmbeddingModel:
    """Embed Chinese text in batches; local mode is a lexical demo fallback."""

    def __init__(self, backend: str | None = None, dimension: int | None = None) -> None:
        self.backend = backend or os.getenv("EMBEDDING_BACKEND", "local")
        self.dimension = dimension or (1024 if self.backend == "bge" else 512)
        self._model = None
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.RLock()

    def _load(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("BAAI/bge-large-zh-v1.5")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return normalized vectors; never silently swap backend on failure."""
        if not texts:
            return []
        with self._lock:
            cached = {
                text: self._cache[text][:]
                for text in dict.fromkeys(texts)
                if text in self._cache
            }
        missing = [text for text in dict.fromkeys(texts) if text not in cached]
        if missing:
            if self.backend == "bge":
                self._load()
                vectors = self._model.encode(missing, normalize_embeddings=True).tolist()
            elif self.backend == "local":
                vectors = [self._lexical_vector(text) for text in missing]
            else:
                raise ValueError(f"Unknown embedding backend: {self.backend}")
            new_vectors = dict(zip(missing, vectors))
            with self._lock:
                for text, vector in zip(missing, vectors):
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    if len(self._cache) > 4096:
                        self._cache.popitem(last=False)
        else:
            new_vectors = {}
        resolved = {**cached, **new_vectors}
        return [resolved[text][:] for text in texts]

    def embed(self, text: str) -> list[float]:
        """Embed a single text."""
        return self.embed_batch([text])[0]

    def _lexical_vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [ch for ch in text.lower() if "\u4e00" <= ch <= "\u9fff"]
        tokens += [text.lower()[i:i + 2] for i in range(max(0, len(text) - 1))]
        for token in tokens:
            index = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big") % self.dimension
            vector[index] += 1
        norm = math.sqrt(sum(value * value for value in vector)) or 1
        return [value / norm for value in vector]
