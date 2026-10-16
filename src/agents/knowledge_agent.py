"""Knowledge agent exposing retrieved context and answerability decision."""

from __future__ import annotations

from src.knowledge.answerable_gate import AnswerableGate
from src.knowledge.rag_engine import RAGEngine

PROCEDURE_QUERIES = {
    "refund_request": "退款 核查 流水",
    "logistics_query": "物流 核查 运单",
    "order_query": "地址 修改 核查",
    "quality_issue": "商品 问题 核查",
    "activity_inquiry": "赠品 活动 核查",
    "authenticity_check": "真伪 核查 规格",
}


class KnowledgeAgent:
    """Retrieve evidence; unverified demo documents are never auto-answerable."""

    def __init__(self, rag_engine: RAGEngine | None = None, gate: AnswerableGate | None = None) -> None:
        self.rag_engine = rag_engine or RAGEngine()
        self.gate = gate or AnswerableGate()

    def search(self, query: str, intent: str = "", user_profile: dict | None = None,
               *, purpose: str = "auto_reply", context: dict | None = None) -> dict:
        """Return ranked evidence with conservative handoff decision."""
        retrieval_query = PROCEDURE_QUERIES.get(intent, query) if purpose == "assistance" else query
        docs = (self.rag_engine.scoped_search(retrieval_query, intent, context)
                if hasattr(self.rag_engine, "scoped_search") else self.rag_engine.hybrid_search(query))
        if purpose == "assistance" and hasattr(self.rag_engine, "scoped_search") and intent in PROCEDURE_QUERIES:
            # Generic unscoped product snippets are noise in operational cases.
            # Keep only explicitly scenario-scoped candidates for human review.
            docs = [doc for doc in docs if isinstance(doc.get("applicable_intents"), list)
                    and intent in doc["applicable_intents"]]
        decision = self.gate.evaluate(query, docs, intent, purpose=purpose, context=context,
                                     procedure_query=retrieval_query if hasattr(self.rag_engine, "scoped_search") else None)
        supported_ids = set(decision["supported_document_ids"])
        approved = [doc for doc in docs if doc.get("id") in supported_ids]
        context = "\n".join(f"[{doc['id']}] {doc.get('title', '')} ({doc.get('source', '')}): "
                            f"{doc.get('content', '')[:400]}" for doc in approved[:3])
        return {"retrieved_docs": docs, "context": context, "confidence": decision["confidence"],
                "can_auto_reply": decision["can_auto_reply"], "reason": decision["reason"],
                "supported_document_ids": decision["supported_document_ids"],
                "approved_docs": approved,
                "can_use_for_assistance": decision.get("can_use_for_assistance", False),
                "procedure_document_ids": decision.get("procedure_document_ids", []),
                "retrieval_query": retrieval_query,
                "procedure_context": "\n".join(
                    f"[{doc['id']}] {doc.get('content', '')[:400]}"
                    for doc in docs if str(doc.get("id")) in decision.get("procedure_document_ids", [])
                )}
