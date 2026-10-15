"""Accuracy and cost safeguards with explicit assumptions, not heldout-label tuning."""

import copy
import json

import pytest

from src.agents.assist_agent import AssistAgent, AssistanceDraft
from src.agents.intent_agent import IntentAgent
from src.agents.emotion_agent import EmotionAgent
from src.optimization.evidence_routing import evidence_draft
from tests.test_service_guidance import context, draft, Model, NoKnowledge


@pytest.mark.parametrize("text,intent", [
    ("我不要退货，只想核对包裹到哪", "logistics_query"),
    ("退回款要核实，不咨询订单成分", "refund_request"),
    ("先核保价，不能补差再考虑退货", "general_consultation"),
    ("没有申请退款，只想改地址", "order_query"),
    ("瓶子有破损，我申请退款", "refund_request"),
    ("订单什么时候发货", "logistics_query"),
    ("不给用法问题，想查防伪", "authenticity_check"),
    ("退款之外不问了", "refund_request"),
    ("想了解含什么原料", "ingredient_query"),
    ("没效果很失望，先问能怎么处理", "effect_inquiry"),
])
def test_explicit_request_dominates_generic_words(text, intent):
    assert IntentAgent().classify(text)["intent_name"] == intent


@pytest.mark.parametrize("text,basic,scene", [
    ("钱没到，特别着急，没有皮肤不适", "fearful", None),
    ("刚买就降价，真不合理", "angry", "price_dissatisfaction"),
    ("谢谢，但还是没收到退款，非常焦虑", "fearful", None),
    ("不满意这个处理方式", "angry", None),
    ("没有不满意，问题处理好了，谢谢", "happy", "satisfaction"),
    ("有没有满意的使用体验可以介绍", "neutral", None),
    ("怕会过敏，目前未使用", "fearful", "allergy_anxiety"),
    ("不怀疑假货，也不担心，只查成分", "neutral", None),
    ("用了没效果，我很失望", "sad", "effect_disappointment"),
])
def test_basic_and_scene_labels_are_not_one_overriding_enum(text, basic, scene):
    result = EmotionAgent().analyze(text)
    assert result["basic_emotion"] == basic
    assert result["special_emotion"] == scene
    assert result["confidence_scope"] != "calibrated probability"


def shipment():
    ctx = context()
    ctx["latest_buyer_message"] = "我的面膜发货了吗？单号多少"
    return ctx


def test_cited_shipment_skips_model_and_retrieval_but_keeps_checks():
    model = Model(draft())
    class ForbiddenKnowledge:
        def search(self, *args):
            raise AssertionError("Verified fact route must not retrieve.")
    result = AssistAgent(model, ForbiddenKnowledge()).assist(
        shipment(), "我的面膜发货了吗？单号多少", "NEW")
    assert model.calls == 0
    assert result["model_status"] == "rule_evidence"
    assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert result["evidence_ids"] == ["ORDER-X"]
    assert "WAYBILL-X" in result["suggested_reply"]
    assert result["final_claim_checks"]
    assert not result["final_validation_flags"]


@pytest.mark.parametrize("variant", [
    "future", "missing_waybill", "two_orders", "ticket", "previous_buyer",
    "risk", "negative", "mismatched_order",
])
def test_ambiguous_or_risky_fact_route_falls_back_to_generation(variant):
    ctx = shipment()
    message = "发货了吗？单号多少"
    agent = AssistAgent(Model(draft()), NoKnowledge())
    signals = agent.inspect(ctx, message, "NEW", "A")
    if variant == "future":
        ctx["evidence"][0]["fields"]["发货时间"] = "2026-06-10 08:00:00"
    elif variant == "missing_waybill":
        ctx["evidence"][0]["fields"].pop("物流单号")
    elif variant == "two_orders":
        ctx["evidence"].append(copy.deepcopy(ctx["evidence"][0]))
    elif variant == "ticket":
        ctx["evidence"].append({"id": "T", "type": "ticket", "fields": {}})
    elif variant == "previous_buyer":
        ctx["messages"].append({"角色": "买家", "message_id": "OLD", "message_text": "退款有问题"})
    elif variant == "risk":
        signals["risk_level_rule"] = "high"
    elif variant == "negative":
        signals["valence"] = -0.7
    else:
        message = "订单OTHER-ORDER发货了吗？单号多少"
    assert evidence_draft(ctx, message, signals) is None


def test_greeting_routes_only_when_no_business_context_is_present():
    ctx = context()
    ctx["evidence"] = []
    model = Model(draft())
    result = AssistAgent(model, NoKnowledge()).assist(ctx, "您好，在吗", "NEW")
    assert result["model_status"] == "rule_evidence" and model.calls == 0
    ctx["evidence"] = context()["evidence"]
    assert evidence_draft(ctx, "您好，在吗", AssistAgent().inspect(ctx, "您好，在吗", "NEW", "A")) is None


@pytest.mark.parametrize("message", [
    "发货了吗？这个商品的成分含酒精吗",
    "单号多少？赠品是不是会分开发",
    "发货了吗？适合敏感肤质吗",
])
def test_mixed_business_and_product_questions_are_never_rule_shortcuts(message):
    ctx = shipment()
    signals = AssistAgent().inspect(ctx, message, "NEW", "A")
    assert evidence_draft(ctx, message, signals) is None


def test_compact_schema_preserves_all_bounds_and_accepts_both_wire_versions():
    legacy = draft()
    compact = AssistanceDraft.model_validate(legacy).model_dump(by_alias=True)
    assert set(compact) == {"s", "e", "r", "i", "m", "a", "n"}
    assert AssistanceDraft.model_validate(compact).model_dump() == legacy
    schema = AssistanceDraft.inference_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["r"]["enum"] == ["低", "中", "高", "紧急"]
    assert schema["properties"]["a"]["maxLength"] == 500
    assert "t" in schema["required"]
    assert "title" not in json.dumps(schema)
    with pytest.raises(ValueError):
        AssistanceDraft.model_validate({**compact, "i": "NOT-ARRAY"})


def test_explicit_emotion_cues_are_audited_instead_of_erased():
    model = Model(draft(emotion="neutral"))
    result = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False).assist(
        context(), "我的退款特别着急，还没有到", "NEW")
    assert result["emotion"] == "担忧"
    assert result["emotion_model"] == "neutral"
    assert result["emotion_source"] == "explicit_rule_cue"
    assert result["draft_before_validation"]["emotion"] == "neutral"
    assert any(x["field"] == "emotion" for x in result["quality_adjustments"])


def test_same_generation_supplies_ambiguous_intent_without_extra_call():
    model = Model({**draft(), "t": "quality_issue"})
    result = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False).assist(
        context(), "这一件和描述对不上，先看看", "NEW")
    assert result["intent"] == "quality_issue" and result["intent_source"] == "model"
    assert result["intent_model"] == "quality_issue"
    assert model.calls == 1


def test_model_intent_cannot_override_explicit_request_or_rule_risk_floor():
    model = Model({**draft(), "t": "general_consultation"})
    result = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False).assist(
        context(), "用后红疹，我想退款", "NEW")
    assert result["intent"] == "allergy_reaction"
    assert result["risk_level"] == "紧急"
    assert model.calls == 1
