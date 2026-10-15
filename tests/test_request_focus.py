"""Current request, reported absence and safety remain separate contracts."""

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.intent_agent import IntentAgent
from src.knowledge.service_guidance import service_focus
from src.utils.service_requests import current_request_text
from tests.test_service_guidance import Model, NoKnowledge, context, draft


@pytest.mark.parametrize("text,intent,focus", [
    ("不改地址了，我要退款", "refund_request", "refund_status_or_amount"),
    ("不查赠品，只问发货了没", "logistics_query", "shipment_query"),
    ("不怀疑假货，只是色号发错了", "quality_issue", "sku_mismatch"),
    ("不用退货退款，只核对发货时间", "logistics_query", "shipment_query"),
    ("没有申请退款，只想改地址", "order_query", "address_change"),
    ("收到货没有赠品，帮查是否分包", "activity_inquiry", "promotion_or_gift"),
])
def test_intent_and_focus_follow_current_request(text, intent, focus):
    predicted = IntentAgent().classify(text)["intent_name"]
    assert predicted == intent
    assert service_focus(text, predicted)["category"] == focus


@pytest.mark.parametrize("text", [
    "没有赠品", "没有退款到账", "退款没到账", "没有发货",
    "没有小样", "用了没有效果", "不是很满意，想退款",
])
def test_missing_outcomes_are_not_deleted_as_declined_requests(text):
    assert current_request_text(text) == text


def test_refund_failure_remains_a_refund_problem():
    assert IntentAgent().classify("没有退款到账，退货已经寄回")["intent_name"] == "refund_request"
    assert service_focus("没有退款到账，退货已经寄回", "refund_request")["category"] == "return_refund"


def test_later_active_request_is_kept_even_if_same_topic_previously_declined():
    text = "不用申请退款，先查物流。如果收不到我再申请退款"
    view = current_request_text(text)
    assert "物流" in view and "我再申请退款" in view
    assert text.startswith("不用申请退款")


def test_original_chat_is_preserved_and_safety_is_not_filtered():
    text = "不要求退款，但用了以后全脸发红"
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    signals = agent.inspect(context(), text, "NEW", "A")
    assert signals["intent"] == "allergy_reaction"
    assert signals["service_focus"]["category"] == "adverse_reaction_report"
    assert signals["risk_level_rule"] == "critical"
    prompt = agent.build_prompt(context(), text, "NEW", signals)
    assert text in prompt
    assert any(item["code"] == "allergy" for item in signals["rule_alerts"])


def test_final_next_action_uses_new_focus_without_extra_model_call():
    model = Model(draft(next_action="核对物流节点能否改址"))
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(context(), "不改地址了，我要退款", "NEW")
    assert result["intent"] == "refund_request"
    assert result["service_focus"]["category"] == "refund_status_or_amount"
    assert "退款流水" in result["next_action"]
    assert "改址" not in result["next_action"]
    assert model.calls == 1
