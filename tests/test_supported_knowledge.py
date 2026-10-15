"""Ranking does not grant approval, and approval does not spill into other documents."""

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.knowledge.answerable_gate import AnswerableGate
from src.knowledge.rag_engine import RAGEngine
from src.models.lightweight_classifier import TfidfDocumentReranker
from src.orchestration.langgraph_workflow import CustomerServiceWorkflow


def documents():
    return [
        {"id": "GOOD", "title": "保湿方法", "content": "保湿方法应依审核商品说明",
         "source": "engineering_fixture", "verified": True},
        {"id": "REJECTED", "title": "保湿方法", "content": "保湿方法，保证一天恢复",
         "source": "engineering_fixture", "verified": True, "approved_product_claim": False},
        {"id": "OTHER", "title": "运费", "content": "运费示例信息",
         "source": "engineering_fixture", "verified": True},
        {"id": "UNKNOWN", "title": "保湿方法", "content": "保湿方法暂无审核依据",
         "source": "engineering_fixture", "verified": True},
    ]


def test_query_approval_selects_only_individually_supported_documents():
    decision = AnswerableGate().evaluate("保湿方法", documents(), "usage_method")
    assert decision["can_auto_reply"]
    assert decision["supported_document_ids"] == ["GOOD"]


def test_wrong_product_cannot_borrow_approval_from_another_document():
    docs = [
        {"id": "A", "title": "ABC成分", "content": "ABC成分包含什么",
         "source": "engineering_fixture", "verified": True,
         "approved_product_claim": True, "product_name": "XYZ"},
        {"id": "B", "title": "储存", "content": "避开高温",
         "source": "engineering_fixture", "verified": True,
         "approved_product_claim": True, "product_name": "ABC"},
    ]
    result = AnswerableGate().evaluate("ABC成分包含什么", docs, "ingredient_query")
    assert not result["can_auto_reply"] and result["supported_document_ids"] == []


def test_sensitive_queries_never_gain_auto_approval_from_ranking():
    result = AnswerableGate().evaluate("使用后不适", documents(), "allergy_reaction")
    assert result["supported_document_ids"] == [] and not result["can_auto_reply"]


def test_knowledge_agent_keeps_candidate_metadata_but_not_blocked_context():
    class Retrieval:
        def hybrid_search(self, query):
            return documents()

    result = KnowledgeAgent(Retrieval()).search("保湿方法", "usage_method")
    assert len(result["retrieved_docs"]) == 4
    assert len(result["approved_docs"]) == 1
    assert "一天恢复" not in result["context"] and "运费" not in result["context"]


def test_assistance_prompt_cannot_inherit_all_candidates_from_one_approved_fact():
    class Retrieval:
        def hybrid_search(self, query):
            return documents()

    result = AssistAgent(knowledge_agent=KnowledgeAgent(Retrieval())).retrieve_knowledge(
        "保湿方法", "usage_method")
    assert "[GOOD]" in result["verified_context"]
    assert "一天恢复" not in result["verified_context"] and "运费" not in result["verified_context"]


def test_legacy_supported_flag_without_document_approval_never_exposes_body():
    class UnscopedKnowledge:
        def search(self, query, intent):
            return {"reason": "supported", "confidence": 1, "can_auto_reply": True,
                    "retrieved_docs": documents()}

    result = AssistAgent(knowledge_agent=UnscopedKnowledge()).retrieve_knowledge("保湿方法", "usage_method")
    assert result["verified_context"] == ""


def test_legacy_workflow_passes_only_individually_approved_documents_to_response():
    class Retrieval:
        def hybrid_search(self, query):
            return documents()

    workflow = CustomerServiceWorkflow(None, None, KnowledgeAgent(Retrieval()), None, None)
    result = workflow.knowledge_node({
        "user_input": "保湿方法", "intent": "usage_method", "user_profile": {},
    })
    assert result["can_auto_reply"]
    assert [doc["id"] for doc in result["approved_docs"]] == ["GOOD"]


@pytest.mark.parametrize("corruption", ["content", "verified", "id"])
def test_second_stage_ranker_cannot_rewrite_knowledge_or_evidence_identity(corruption):
    class BadRanker:
        def rerank(self, query, candidates):
            return [{**doc, corruption: "CORRUPTED"} for doc in candidates]

    engine = RAGEngine(documents=documents(), reranker=BadRanker())
    with pytest.raises(ValueError, match="Reranker"):
        engine.hybrid_search("保湿方法")


def test_optional_cpu_ranker_reorders_only_and_does_not_approve_documents():
    pytest.importorskip("sklearn")
    docs = documents()
    ranker = TfidfDocumentReranker(docs)
    ranked = ranker.rerank("运费", docs)
    assert ranked[0]["id"] == "OTHER"
    for doc in ranked:
        original = next(item for item in docs if item["id"] == doc["id"])
        assert all(doc[key] == value for key, value in original.items())
    assert not AnswerableGate().evaluate("保湿方法", [ranked[-1]])["can_auto_reply"]


def test_ranker_unknown_ids_are_rejected_before_scoring():
    pytest.importorskip("sklearn")
    with pytest.raises(ValueError, match="unknown"):
        TfidfDocumentReranker(documents()).rerank("保湿", [{"id": "NOT-IN-CORPUS"}])
