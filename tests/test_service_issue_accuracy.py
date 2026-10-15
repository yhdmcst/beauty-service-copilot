"""Specific issues and emotional allegations must not erase denials or source boundaries."""

import copy

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.emotion_agent import EmotionAgent
from src.agents.intent_agent import IntentAgent
from src.knowledge.service_guidance import review_guidance, service_focus
from src.utils.service_issue_cues import reported_item_issues
from tests.test_service_guidance import Model, NoKnowledge, context, draft


@pytest.mark.parametrize("text,focus", [
    ("纸盒完整，里面是空管，遮瑕没法用", "product_usability_or_damage"),
    ("瓶盖开裂，物流已收到", "product_usability_or_damage"),
    ("包裹到了，但少一瓶精华", "missing_items"),
    ("订三支只收到两支", "missing_items"),
    ("箱子打开是空的，帮查出库", "missing_items"),
])
def test_product_problem_is_not_hidden_by_delivery_terms(text, focus):
    intent = IntentAgent().classify(text)["intent_name"]
    assert intent == "quality_issue"
    assert service_focus(text, intent)["category"] == focus
    assert all(text[item["start"]:item["end"]] == item["quote"]
               for item in reported_item_issues(text))


@pytest.mark.parametrize("text", [
    "没有少件或破损，只查运单",
    "瓶身没有碎裂，只问用法",
    "不是漏发，查一下配送",
    "如果少一瓶，我该怎样处理",
    "朋友说包裹空的，我只问成分",
    "买两支只收到一盒，里面装两支",
    "空瓶回收怎么参加",
])
def test_denials_hypotheticals_other_people_and_different_units_are_not_reported_defects(text):
    assert reported_item_issues(text) == []


def test_refund_request_and_adverse_safety_take_priority_over_damage():
    agent = AssistAgent(Model(draft()), NoKnowledge())
    refund = agent.inspect(context(), "少一支，现在申请退款", "NEW", "A")
    assert refund["intent"] == "refund_request"
    assert refund["service_focus"]["category"] == "refund_status_or_amount"
    adverse = agent.inspect(context(), "泵头破损，但用后脸上红肿，很担心", "NEW", "A")
    assert adverse["intent"] == "allergy_reaction" and adverse["risk_level_rule"] == "critical"


def test_gift_absence_remains_promotion_problem():
    message = "没有赠品，活动说明买一送一，查是否分包"
    result = IntentAgent().classify(message)
    assert result["intent_name"] == "activity_inquiry"
    assert service_focus(message, result["intent_name"])["category"] == "promotion_or_gift"


@pytest.mark.parametrize("text", [
    "盒子内少了洁面乳，其余都在",
    "包裹到了但漏了粉底液",
    "正装没放进去，查清单",
])
def test_concrete_missing_product_without_quantity_is_not_delivery_question(text):
    result = IntentAgent().classify(text)
    assert result["intent_name"] == "quality_issue"
    assert service_focus(text, result["intent_name"])["category"] == "missing_items"


@pytest.mark.parametrize("text,basic", [
    ("退款没到，是不是骗人啊", "angry"),
    ("难道不是在敷衍我吗", "angry"),
    ("是否在骗人，钱在哪里", "angry"),
    ("不是在骗人，是在解释记录", "neutral"),
    ("没有骗人，只咨询使用步骤", "neutral"),
    ("他在说骗人，我自己没有生气", "neutral"),
])
def test_allegation_question_and_genuine_denial_are_different(text, basic):
    assert EmotionAgent().analyze(text)["basic_emotion"] == basic


def test_missing_item_next_step_reuses_known_quantity_and_checks_warehouse():
    model = Model(draft(next_action="买家查物流是否送达"))
    result = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False).assist(
        context(), "买了三瓶只收到两瓶", "NEW")
    assert result["intent"] == "quality_issue"
    assert "装箱" in result["next_action"] and "数量" in result["next_action"]
    assert model.calls == 1


def test_unconditional_material_request_is_repaired_without_claiming_receipt():
    ctx = context()
    original = copy.deepcopy(ctx)
    message = "照片已经提供，泵头按不出"
    candidate = draft(
        suggested_reply="泵头用不了，需要查商品情况。请您再次提供照片。核实后协商处理。",
        next_action="客服核商品与已有材料，协商售后",
    )
    reviewed = review_guidance(candidate, ctx, message, service_focus(message, "quality_issue"))
    assert any(item["code"] == "reported_material_requested_again" for item in reviewed["issues"])
    corrected = reviewed["changes"]["suggested_reply"]
    assert "先核材料是否收到及可用" in corrected
    assert "再次提供" not in corrected and "收到照片了" not in corrected
    assert "核实后协商处理" in corrected and ctx == original


@pytest.mark.parametrize("message,reply", [
    ("照片还没发，泵头坏了", "请您提供照片。"),
    ("照片已经提供，泵头坏了", "如果照片无法找到，再请您提供照片。"),
    ("照片已经提供，泵头坏了", "照片还缺的话再请您补充。"),
])
def test_missing_or_unusable_material_can_be_requested_conditionally(message, reply):
    reviewed = review_guidance(draft(suggested_reply=reply), context(), message,
                              service_focus(message, "quality_issue"))
    assert not any(item["code"] == "reported_material_requested_again" for item in reviewed["issues"])
