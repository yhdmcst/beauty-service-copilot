"""Compare optional lexical second-stage ranking on fixed engineering fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.knowledge.answerable_gate import AnswerableGate
from src.knowledge.rag_engine import RAGEngine
from src.models.lightweight_classifier import TfidfDocumentReranker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Retain earlier retrieval evidence.")
    path = ROOT / "evaluation/knowledge_reranking_protocol_20261014.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    docs = protocol["documents"]
    baseline = RAGEngine(documents=docs)
    reranked = RAGEngine(documents=docs, reranker=TfidfDocumentReranker(docs))
    rows = []
    for query in protocol["queries"]:
        measurements = {}
        for name, engine in (("original", baseline), ("reranked", reranked)):
            stamp = time.perf_counter()
            found = engine.hybrid_search(query["text"], top_k=3)
            measurements[name] = {
                "ids": [doc["id"] for doc in found],
                "top1_match": bool(found) and found[0]["id"] == query["expected_document_id"],
                "wall_ms": (time.perf_counter() - stamp) * 1000,
                "can_auto_reply": AnswerableGate().evaluate(query["text"], found)["can_auto_reply"],
            }
        rows.append({**query, **measurements})
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "scope": protocol["scope"],
        "human_gold": False, "live_reranking_enabled": False, "large_model_calls": 0,
        "protocol_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "summary": {
            name: {"n": len(rows), "top1_match_n": sum(row[name]["top1_match"] for row in rows),
                   "auto_reply_n": sum(row[name]["can_auto_reply"] for row in rows)}
            for name in ("original", "reranked")
        }, "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
