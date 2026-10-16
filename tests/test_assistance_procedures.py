"""Procedures guide human actions without granting factual/auto-reply approval."""

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.knowledge.answerable_gate import AnswerableGate
from src.ops.case_store import CaseStore


def procedure(**changes):
    return {"id": "REFUND-PROCESS", "title": "退款核查", "content": "客服核对退款流水和原支付渠道。",
            "verified": True, "source": "engineering_fixture_not_brand_policy",
            "knowledge_type": "service_procedure", "usage_scope": "human_assistance_only",
            "review_status": "approved", "applicable_intents": ["refund_request"], **changes}


def test_sensitive_intent_can_use_reviewed_steps_without_fact_approval():
    result = AnswerableGate().evaluate("退款", [procedure()], "refund_request", purpose="assistance")
    assert result["can_use_for_assistance"]
    assert result["procedure_document_ids"] == ["REFUND-PROCESS"]
    assert result["supported_document_ids"] == [] and not result["can_auto_reply"]
    auto = AnswerableGate().evaluate("退款", [procedure()], "refund_request")
    assert not auto["can_auto_reply"] and not auto["supported_document_ids"]


@pytest.mark.parametrize("changes", [
    {"verified": False}, {"review_status": "draft"}, {"usage_scope": "all"},
    {"applicable_intents": ["logistics_query"]}, {"source": "模拟样本"},
    {"knowledge_type": "policy"}, {"applicable_intents": "refund_request"},
])
def test_unreviewed_or_inapplicable_procedure_is_not_exposed(changes):
    result = AnswerableGate().evaluate("退款", [procedure(**changes)], "refund_request", purpose="assistance")
    assert not result["can_use_for_assistance"]
    assert result["procedure_document_ids"] == []


def test_procedure_reaches_only_assistance_prompt_channel():
    class Retrieval:
        def hybrid_search(self, query):
            return [procedure(), procedure(id="UNVERIFIED", verified=False, content="保证当天到账")]
    knowledge = AssistAgent(knowledge_agent=KnowledgeAgent(Retrieval())).retrieve_knowledge("退款", "refund_request")
    assert not knowledge["verified_context"]
    assert "退款流水" in knowledge["procedure_context"]
    assert "当天到账" not in knowledge["procedure_context"]
    legacy = KnowledgeAgent(Retrieval()).search("退款", "refund_request")
    assert not legacy["context"] and not legacy["procedure_context"]


def test_unrelated_procedure_cannot_borrow_intent_approval():
    result = AnswerableGate().evaluate(
        "赠品少件", [procedure()], "refund_request", purpose="assistance")
    assert not result["can_use_for_assistance"]


def test_repeated_risk_upgrades_existing_task_and_retains_evidence_history():
    store = CaseStore()
    first = store.create_task("S1", "核查投诉", "首次反馈", priority="medium", risk_code="complaint")
    second = store.create_task("S1", "核查投诉", "新增严重投诉", priority="high", risk_code="complaint")
    assert second["task_id"] == first["task_id"] and second["priority"] == "high"
    assert any(item["action"] == "escalated" for item in second["history"])
    assert any(item["note"] == "首次反馈" for item in second["history"])
    assert any(item["note"] == "新增严重投诉" for item in second["history"])
    third = store.create_task("S1", "核查投诉", "新增严重投诉", priority="low", risk_code="complaint")
    assert third["priority"] == "high" and third["history"] == second["history"]
    assert len(store.list_tasks()) == 1
    store.close()
