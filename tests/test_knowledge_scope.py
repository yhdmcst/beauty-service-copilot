import pytest

from src.agents.knowledge_agent import KnowledgeAgent
from src.knowledge.rag_engine import RAGEngine, load_documents
from src.knowledge.answerable_gate import AnswerableGate
from src.knowledge.knowledge_scope import eligible_document
from tests.test_assistance_procedures import procedure


@pytest.mark.parametrize("metadata,context,allowed", [
    ({"brand": "A"}, {}, False), ({"brand": "A"}, {"brand": "B"}, False),
    ({"brand": "A"}, {"brand": "A"}, True),
    ({"effective_from": "2026-01-01"}, {}, False),
    ({"effective_to": "2026-06-01"}, {"analysis_at": "2026-06-02 10:00:00"}, False),
    ({"effective_from": "2026-01-01", "effective_to": "2026-12-31"}, {"analysis_at": "2026-06-02"}, True),
    ({"effective_from": "bad-date"}, {"analysis_at": "2026-06-02"}, False),
    ({"review_status": "retired"}, {}, False),
    ({"applicable_intents": ["quality_issue"]}, {}, False),
])
def test_scope_is_independent_of_similarity(metadata, context, allowed):
    assert eligible_document(metadata, "refund_request", context) is allowed


def test_filters_precede_final_top_k_and_gate_rechecks_scope():
    docs = [procedure(id=f"wrong-{i}", brand="WRONG") for i in range(8)] + [procedure(id="eligible")]
    agent = KnowledgeAgent(RAGEngine(documents=docs))
    result = agent.search("这笔钱到底什么时候回来", "refund_request", purpose="assistance")
    assert [doc["id"] for doc in result["retrieved_docs"]] == ["eligible"]
    assert result["procedure_document_ids"] == ["eligible"]
    blocked = AnswerableGate().evaluate("退款", [procedure(brand="WRONG")], "refund_request", purpose="assistance")
    assert blocked["procedure_document_ids"] == []


def test_default_procedures_do_not_grant_mock_facts_brand_or_auto_approval():
    docs = load_documents()
    procedures = [doc for doc in docs if doc.get("knowledge_type") == "service_procedure"]
    assert len(procedures) == 6
    assert all("工程" in doc["review_basis"] for doc in procedures)
    assert not any(doc.get("verified") for doc in docs if doc not in procedures)
    result = KnowledgeAgent(RAGEngine(documents=docs)).search("钱还没回来", "refund_request", purpose="assistance")
    assert result["procedure_document_ids"] == ["procedure-refund-v1"]
    assert not result["can_auto_reply"] and not result["supported_document_ids"]
    assert [doc["id"] for doc in result["retrieved_docs"]] == ["procedure-refund-v1"]
