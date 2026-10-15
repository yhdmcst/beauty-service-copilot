"""Communication needs must be source-bound and must not fabricate human reviews."""

import copy
import json

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.emotion_agent import EmotionAgent
from src.knowledge.communication_brief import communication_brief
from src.risk.beauty_risk_rules import detect_risks
from tests.test_service_guidance import Model, NoKnowledge, context, draft


@pytest.mark.parametrize("text,basic,scene", [
    ("您建议过敏处理吗，目前未使用", "neutral", None),
    ("谢谢，请问是否适合油皮", "neutral", None),
    ("单号给过了，别再问了，这问题说了三遍", "angry", None),
    ("你们可真行，又让我等了三天", "angry", None),
    ("我说的是他生气，我自己没有生气", "neutral", None),
    ("请问投诉入口在哪，想了解流程", "neutral", None),
    ("非常满意，处理得很好，谢谢", "happy", "satisfaction"),
])
def test_customer_emotion_not_politeness_symptom_question_or_other_person(text, basic, scene):
    result = EmotionAgent().analyze(text)
    assert result["basic_emotion"] == basic
    assert result["special_emotion"] == scene


def test_needs_and_self_reported_preferences_keep_source_ids_without_mutation():
    ctx = context()
    ctx["messages"] = [
        {"角色": "买家", "message_id": "OLD1", "发送时间": "2026-06-08 10:00:00",
         "message_text": "我是敏感肌，订单号已经提供"},
        {"角色": "客服", "message_id": "STAFF", "发送时间": "2026-06-08 10:02:00",
         "message_text": "您是油皮"},
        {"角色": "买家", "message_id": "FUTURE", "发送时间": "2026-06-08 12:00:00",
         "message_text": "我是干皮"},
    ]
    original = copy.deepcopy(ctx)
    message = "单号给过了，别再问了，退款一直没到账"
    agent = AssistAgent(Model(draft()), NoKnowledge())
    signals = agent.inspect(ctx, message, "NEW", "A")
    brief = signals["communication_brief"]
    assert ctx == original
    assert brief["additional_model_calls"] == 0
    assert {item["code"] for item in brief["needs"]} == {"repeated_information", "waiting_for_resolution"}
    assert brief["stated_preferences"][0]["value"] == "敏感肌"
    assert brief["stated_preferences"][0]["basis"]["message_id"] == "OLD1"
    assert "油皮" not in str(brief) and "干皮" not in str(brief)
    assert "性格" not in str(brief)


def test_skin_question_is_not_rewritten_as_self_report():
    ctx = context()
    signals = AssistAgent().inspect(ctx, "敏感肌是否适合这款？", "NEW", "A")
    assert not signals["communication_brief"]["stated_preferences"]


def test_conflicting_skin_statements_are_not_silently_resolved():
    ctx = context()
    ctx["messages"] = [{"角色": "买家", "message_id": "OLD", "发送时间": "2026-06-08 10:00:00",
                        "message_text": "我是油皮"}]
    signals = AssistAgent().inspect(ctx, "我是干皮，想查用法", "NEW", "A")
    assert len(signals["communication_brief"]["stated_preferences"]) == 2
    assert any("不同表达" in item for item in signals["communication_brief"]["human_review_reasons"])


def test_communication_prompt_adds_no_second_model_and_cache_still_has_fresh_id():
    ctx = context()
    message = "我是敏感肌，订单号已经提供，别再问了"
    model = Model(draft())
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    first = agent.assist(ctx, message, "NEW", "A1")
    second = agent.assist(ctx, message, "NEW", "A2")
    assert model.calls == 1
    assert second["cache_hit"] and second["analysis_id"] == "A2"
    assert first["communication_brief"]["stated_preferences"][0]["value"] == "敏感肌"
    assert first["model_status"] != "fallback"


def test_unknown_context_never_creates_resolved_or_satisfied_claim():
    ctx = context()
    signals = AssistAgent().inspect(ctx, "退款还没到账，谢谢", "NEW", "A")
    brief = communication_brief(ctx, "退款还没到账，谢谢", signals)
    assert signals["emotion_basic"] != "happy"
    assert any(item["code"] == "waiting_for_resolution" for item in brief["needs"])


def test_product_given_to_someone_is_not_repeated_customer_information():
    signals = AssistAgent().inspect(context(), "我已经给朋友用了这款面霜，想问用法", "NEW", "A")
    assert "repeated_information" not in {
        item["code"] for item in signals["communication_brief"]["needs"]
    }


def test_model_emotion_can_refine_communication_strategy_without_changing_risk_floor():
    model = Model(draft(emotion="fearful"))
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(context(), "还需要再了解一下", "NEW")
    assert result["emotion"] == "担忧"
    assert "担忧" in result["communication_brief"]["strategy"]
    assert model.calls == 1


@pytest.mark.parametrize("message", [
    "昨夜涂完精华，今天脸上又红又痒",
    "用了修护霜。现在两颊红且痒，是不是有问题",
])
def test_reported_paired_symptoms_keep_safety_floor_without_requiring_emotion(message):
    signals = AssistAgent().inspect(context(), message, "NEW", "A")
    assert signals["risk_level_rule"] == "critical"
    assert any(alert["code"] == "allergy" for alert in signals["rule_alerts"])
    assert signals["service_focus"]["category"] == "adverse_reaction_report"


@pytest.mark.parametrize("message", [
    "尚未用了这款，担心会又红又痒",
    "以前用了另一款，现在没有又红又痒，只查物流",
    "用了这款之后会不会又红又痒",
])
def test_paired_symptom_question_or_denial_is_not_active_reaction(message):
    assert not any(alert["code"] == "allergy" for alert in detect_risks(message))


def test_repeated_information_does_not_displace_adverse_reaction_strategy():
    signals = AssistAgent().inspect(
        context(), "照片已经提供，别再问，涂完面霜两颊又红又痒", "NEW", "A")
    assert "优先人工跟进" in signals["communication_brief"]["strategy"]
    assert any(item["code"] == "repeated_information"
               for item in signals["communication_brief"]["needs"])


def test_future_emotion_cannot_change_current_replay_risk():
    ctx = context()
    baseline = AssistAgent().inspect(ctx, "难过", "NEW", "A")
    ctx["messages"] = [{
        "角色": "买家", "message_id": "FUTURE", "发送时间": "2026-06-08 12:00:00",
        "message_text": "很满意，喜欢，好用",
    }]
    signals = AssistAgent().inspect(ctx, "难过", "NEW", "A")
    assert signals["emotion_trend"] == baseline["emotion_trend"]
    assert signals["risk_level_rule"] == baseline["risk_level_rule"]


def test_future_adverse_reaction_message_cannot_create_historical_replay_alert():
    ctx = context()
    ctx["messages"] = [{
        "角色": "买家", "message_id": "FUTURE", "发送时间": "2026-06-08 12:00:00",
        "message_text": "涂完面霜脸肿了",
    }]
    signals = AssistAgent().inspect(ctx, "现在只想查运单", "NEW", "A")
    assert not any(alert["code"] == "historical_adverse_reaction"
                   for alert in signals["rule_alerts"])


def test_weak_rule_emotion_does_not_anchor_model_input():
    agent = AssistAgent()
    signals = agent.inspect(context(), "这事拖多久了，还是没有结果", "NEW", "A")
    payload = json.loads(agent.build_prompt(context(), "这事拖多久了，还是没有结果", "NEW", signals).splitlines()[2])
    assert "emotion" not in payload["signals"]
    assert "emotion_scene" not in payload["signals"]
    assert payload["signals"]["rule_risk"] == signals["risk_level_rule"]


def test_strong_rule_emotion_and_safety_floor_remain_in_prompt():
    agent = AssistAgent()
    signals = agent.inspect(context(), "我很担心，用后脸部红肿", "NEW", "A")
    payload = json.loads(agent.build_prompt(context(), "我很担心，用后脸部红肿", "NEW", signals).splitlines()[2])
    assert payload["signals"]["emotion"] == "fearful"
    assert payload["signals"]["rule_risk"] == "critical"
