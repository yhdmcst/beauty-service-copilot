"""Conservative gate: evidence sufficiency is distinct from retrieval score."""

from __future__ import annotations

import re

from src.knowledge.rag_engine import tokenize
from src.knowledge.knowledge_scope import eligible_document

UNVERIFIED = ("模拟样本", "演示政策", "未经平台核实", "非知乎实采", "非小红书实采")
UNCERTAIN = ("暂无", "无法确认", "不能确认", "不确定", "未提供", "未知", "没有配方")
SENSITIVE_INTENTS = {"allergy_reaction", "order_query", "logistics_query", "refund_request",
                     "quality_issue", "authenticity_check", "invoice_request"}


class AnswerableGate:
    """Require verified evidence and product-specific support before auto reply."""

    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold

    def evaluate(self, query: str, docs: list[dict], intent: str = "", *, purpose: str = "auto_reply",
                 context: dict | None = None, procedure_query: str | None = None) -> dict:
        """Return decision and calibrated heuristic confidence (not a probability)."""
        if purpose not in {"auto_reply", "assistance"}:
            raise ValueError("Unknown knowledge purpose")
        docs = [doc for doc in docs if eligible_document(doc, intent, context)]
        if purpose == "assistance":
            # Procedures may guide a human's next step, never establish an order
            # state, policy entitlement, diagnosis, or product claim.
            terms = tokenize(procedure_query or query)
            query_tokens = {token for token in terms if len(token) > 1} or set(terms)
            procedures = [doc for doc in docs if doc.get("verified") is True
                          and doc.get("knowledge_type") == "service_procedure"
                          and doc.get("usage_scope") == "human_assistance_only"
                          and doc.get("review_status") == "approved"
                          and isinstance(doc.get("applicable_intents"), list)
                          and intent in doc["applicable_intents"]
                          and len(query_tokens & set(tokenize(f"{doc.get('title', '')} {doc.get('content', '')}")))
                          / max(len(query_tokens), 1) >= self.threshold
                          and not any(flag in doc.get("source", "") for flag in UNVERIFIED)]
            regular = self.evaluate(query, [doc for doc in docs
                                          if doc.get("knowledge_type") != "service_procedure"], intent, context=context)
            # Exact intent eligibility is mandatory; lexical ranking alone does
            # not approve a procedure or make it suitable for automatic replies.
            procedure_ids = [str(doc["id"]) for doc in procedures if doc.get("id")]
            return {**regular, "can_use_for_assistance": bool(procedure_ids or regular["supported_document_ids"]),
                    "procedure_document_ids": procedure_ids}
        docs = [doc for doc in docs if doc.get("knowledge_type") != "service_procedure"]
        if intent in SENSITIVE_INTENTS:
            return {"can_auto_reply": False, "confidence": 0.0, "reason": "requires_human_or_order_system",
                    "supported_document_ids": []}
        if not docs:
            return {"can_auto_reply": False, "confidence": 0.0, "reason": "no_evidence",
                    "supported_document_ids": []}
        verified = [doc for doc in docs if doc.get("verified") is True
                    and not any(flag in doc.get("source", "") for flag in UNVERIFIED)]
        if not verified:
            return {"can_auto_reply": False, "confidence": 0.0, "reason": "unverified_evidence",
                    "supported_document_ids": []}
        query_tokens = set(tokenize(query))
        filtered = [token for token in query_tokens if len(token) > 1]
        if not filtered:
            filtered = list(query_tokens)
        product_names = re.findall(r"[A-Za-z][\w-]{2,}", query)
        scores = []
        supported_ids = []
        for doc in verified:
            blocked = any(flag in f"{doc.get('title', '')} {doc.get('content', '')}" for flag in UNCERTAIN) \
                or doc.get("approved_product_claim") is False
            if product_names and not (
                doc.get("approved_product_claim") is True and all(
                    name.lower() in str(doc.get("product_name", "")).lower() for name in product_names)
            ):
                blocked = True
            score = 0.0 if blocked else len(set(filtered) & set(tokenize(
                f"{doc.get('title', '')} {doc.get('content', '')}"))) / max(len(filtered), 1)
            scores.append(score)
            if score >= self.threshold and doc.get("id"):
                supported_ids.append(str(doc["id"]))
        best = max(scores, default=0.0)
        return {"can_auto_reply": best >= self.threshold, "confidence": round(best, 3),
                "reason": "supported" if best >= self.threshold else "insufficient_evidence",
                "supported_document_ids": list(dict.fromkeys(supported_ids))}

    def can_answer(self, query: str, docs: list[dict], intent: str = "") -> bool:
        """Compatibility boolean interface."""
        return self.evaluate(query, docs, intent)["can_auto_reply"]
