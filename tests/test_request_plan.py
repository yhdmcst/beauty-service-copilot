"""New engineering cases: request order, conditions and review are distinct from safety."""

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.intent_agent import IntentAgent
from src.knowledge.service_guidance import service_focus, review_guidance
from src.utils.service_requests import active_request_text, request_plan
from tests.test_service_guidance import Model, NoKnowledge, context, draft


@pytest.mark.parametrize("text,intent,focus", [
    ("先别退款，帮我查一下物流", "logistics_query", "shipment_query"),
    ("退款先不用了，帮我查一下物流", "logistics_query", "shipment_query"),
    ("先查物流，实在找不到再退款", "logistics_query", "shipment_query"),
    ("钱还没回来，别再问订单号了", "refund_request", "refund_status_or_amount"),
    ("上次说不用退款，现在还是给我退了吧", "refund_request", "refund_status_or_amount"),
    ("这单退款，另一单改地址", "refund_request", "refund_status_or_amount"),
    ("之前申请退款一直没到账", "refund_request", "refund_status_or_amount"),
    ("不用退款，先查物流。如果收不到我再退款", "logistics_query", "shipment_query"),
])
def test_current_action_follows_order_and_unresolved_outcomes(text, intent, focus):
    result = IntentAgent().classify(text)
    assert result["intent_name"] == intent
    assert service_focus(text, result["intent_name"])["category"] == focus


def test_plan_preserves_orders_source_spans_and_no_invented_ids():
    text = "这单退款，另一单改地址"
    plan = request_plan(text)
    assert plan["requires_review"]
    assert [(item["intent"], item["order_scope"]) for item in plan["items"]] == [
        ("refund_request", "这单"), ("order_query", "另一单")]
    for item in plan["items"]:
        assert item["quote"] == text[item["start"]:item["end"]]
        assert item["binding_status"] == "unverified"
        assert "order_id" not in item


def test_rule_consultation_does_not_become_an_application():
    plan = request_plan("不是要退款，我只是想问退款规则")
    assert [item["status"] for item in plan["items"]] == ["deferred", "inquiry"]
    assert plan["requires_review"]


def test_conditional_cue_does_not_erase_active_request_in_same_clause():
    text = "先查物流如果找不到再退款"
    view = active_request_text(text)
    assert "物流" in view and "退款" not in view
    assert len(view) == len(text)


def test_repeated_refund_in_one_clause_can_have_different_statuses():
    plan = request_plan("先别退款如果找不到再退款")
    assert [item["status"] for item in plan["items"]] == ["deferred", "conditional"]


@pytest.mark.parametrize("text", ["没有赠品", "退款没到账", "没有发货", "退货后钱还没回来"])
def test_missing_results_remain_active(text):
    assert active_request_text(text) == text


def test_conflict_allows_same_call_model_correction_and_keeps_safety_floor():
    model = Model({**draft(), "t": "logistics_query"})
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    text = "先别退款，帮我查一下物流"
    signals = agent.inspect(context(), text, "NEW", "A")
    assert signals["intent_confidence"] < .90
    prompt = agent.build_prompt(context(), text, "NEW", signals)
    assert '"request_plan"' in prompt and "t=当前主意图" in prompt
    result = agent.assist(context(), text, "NEW")
    assert model.calls == 1
    assert result["intent_source"] == "model"
    assert result["intent"] == "logistics_query"
    assert result["request_plan"]["requires_review"]


def test_safety_keeps_original_input_despite_deferred_refund():
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    result = agent.inspect(context(), "先别退款，但用了后全脸发红", "NEW", "A")
    assert result["intent"] == "allergy_reaction"
    assert result["risk_level_rule"] == "critical"
    assert result["service_focus"]["category"] == "adverse_reaction_report"


def test_plan_survives_cache_and_fallback():
    text = "这单退款，另一单改地址"
    model = Model(draft())
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    first = agent.assist(context(), text, "NEW")
    second = agent.assist(context(), text, "NEW")
    assert second["cache_hit"] and model.calls == 1
    assert first["request_plan"] == second["request_plan"]
    class BrokenModel:
        def generate_with_usage(self, *args, **kwargs):
            raise RuntimeError("offline")
    fallback = AssistAgent(BrokenModel(), NoKnowledge(), enable_evidence_routes=False).assist(context(), text, "NEW")
    assert fallback["model_status"] == "fallback"
    assert fallback["request_plan"] == first["request_plan"]


def test_order_request_sequence_does_not_depend_on_topic_dictionary_order():
    text = "这单改地址另一单退款"
    plan = request_plan(text)
    assert [item["intent"] for item in plan["items"]] == ["order_query", "refund_request"]
    assert IntentAgent().classify(text)["intent_name"] == "order_query"
    assert service_focus(text, "order_query")["category"] == "address_change"


def test_multiple_orders_do_not_lose_second_action_during_rule_repair():
    text = "这单退款，另一单改地址"
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(context(), text, "NEW")
    assert "退款" in result["suggested_reply"] and "修改地址" in result["suggested_reply"]
    assert "对应" in result["next_action"]
    assert result["final_validation_flags"] == []
    assert "对应关系" in "".join(result["missing_info"])
