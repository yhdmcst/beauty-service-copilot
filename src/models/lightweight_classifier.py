"""Optional CPU classification hints; never a safety decision or human label."""

from __future__ import annotations

from collections import Counter
from typing import Iterable


class LightweightTextClassifier:
    """Use scikit-learn character features with a supervised classification head."""

    def __init__(self, labels: Iterable[str]) -> None:
        self.allowed_labels = set(labels)
        self.pipeline = None
        self.training_counts: dict[str, int] = {}

    def fit(self, rows: list[dict], label_field: str) -> "LightweightTextClassifier":
        if not 2 <= len(rows) <= 10000:
            raise ValueError("Require 2-10000 explicitly labeled training examples.")
        for row in rows:
            if not isinstance(row.get("text"), str) or not 1 <= len(row["text"].strip()) <= 2000:
                raise ValueError("Training text must be nonempty and bounded.")
            if row.get(label_field) not in self.allowed_labels:
                raise ValueError("Unknown training label.")
        counts = Counter(row[label_field] for row in rows)
        if len(counts) < 2:
            raise ValueError("At least two distinct training labels are required.")
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
        except ImportError as error:
            raise RuntimeError("Install requirements_research.txt for CPU classification experiments.") from error
        self.pipeline = make_pipeline(
            TfidfVectorizer(analyzer="char", ngram_range=(1, 4), sublinear_tf=True, max_features=20000),
            LogisticRegression(C=4.0, class_weight="balanced", max_iter=1000, random_state=42),
        )
        self.pipeline.fit([row["text"] for row in rows], [row[label_field] for row in rows])
        self.training_counts = dict(counts)
        return self

    def predict(self, texts: list[str], top_k: int = 3) -> list[dict]:
        if self.pipeline is None:
            raise RuntimeError("Fit on a separate training split before prediction.")
        if not 1 <= top_k <= 5 or len(texts) > 128:
            raise ValueError("Prediction batch is at most 128; top_k is 1-5.")
        if any(not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000 for text in texts):
            raise ValueError("Prediction text must be nonempty and bounded.")
        if not texts:
            return []
        vectorizer, classifier = self.pipeline.steps[0][1], self.pipeline.steps[1][1]
        features = vectorizer.transform(texts)
        scores = classifier.predict_proba(features)
        results = []
        for index, probabilities in enumerate(scores):
            ordered = sorted(range(len(probabilities)), key=lambda i: float(probabilities[i]), reverse=True)
            coverage = features[index].nnz > 0
            candidates = [{
                "label": str(classifier.classes_[i]), "score": round(float(probabilities[i]), 6),
                "training_example_n": self.training_counts[str(classifier.classes_[i])],
            } for i in ordered[:top_k]]
            margin = float(probabilities[ordered[0]] - probabilities[ordered[1]])
            results.append({
                "label": candidates[0]["label"] if coverage else None,
                "candidates": candidates if coverage else [], "feature_coverage": coverage,
                "score_margin": round(margin, 6),
                "review_required": not coverage or margin < .10 or float(probabilities[ordered[0]]) < .50,
                "score_scope": "uncalibrated classifier output on limited labeled examples",
                "can_override_service_risk": False, "human_annotation": False,
                "model_calls": 0, "generation_tokens": 0,
            })
        return results


class TfidfDocumentReranker:
    """Optional lexical second-stage ranker; its score never authorizes a claim."""

    def __init__(self, documents: list[dict]) -> None:
        if not documents or any(not doc.get("id") for doc in documents):
            raise ValueError("Reranker requires nonempty documents with stable IDs.")
        if len({doc["id"] for doc in documents}) != len(documents):
            raise ValueError("Duplicate document IDs.")
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), max_features=20000)
        self.ids = {doc["id"]: position for position, doc in enumerate(documents)}
        self.features = self.vectorizer.fit_transform([
            f"{doc.get('title', '')} {doc.get('content', '')}" for doc in documents
        ])

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if any(doc.get("id") not in self.ids for doc in candidates):
            raise ValueError("Cannot rerank unknown document IDs.")
        if len({doc["id"] for doc in candidates}) != len(candidates):
            raise ValueError("Duplicate rerank candidates.")
        if not candidates or not query.strip():
            return candidates
        query_vector = self.vectorizer.transform([query])
        if query_vector.nnz == 0:
            return candidates
        scores = (self.features @ query_vector.T).toarray().ravel()
        return sorted(
            [{**doc, "rerank_score": float(scores[self.ids[doc["id"]]]),
              "rerank_scope": "lexical character TF-IDF; not semantic confidence or approval"}
             for doc in candidates],
            key=lambda doc: doc["rerank_score"], reverse=True,
        )
