"""Targeted cache and unsupported-cause checks for the reviewed release."""

import copy

import pytest

from src.agents.assist_agent import AssistAgent
from src.knowledge.service_guidance import review_guidance, service_focus
from src.optimization.smart_cache import SmartCache
from tests.test_service_guidance import Model, NoKnowledge, context, draft


def test_cached_model_intent_keeps_its_source_and_gets_fresh_analysis_id():
    model = Model({**draft(), "t": "quality_issue"})
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    first = agent.assist(context(), "这一件和描述对不上，先看看", "NEW", "FIRST")
    second = agent.assist(context(), "这一件和描述对不上，先看看", "NEW", "SECOND")
    assert first["intent"] == second["intent"] == "quality_issue"
    assert second["intent_source"] == "model"
    assert first["intent_basis"] == second["intent_basis"] == "model_with_rule_safety_floor"
    assert second["service_focus"] == first["service_focus"]
    assert second["analysis_id"] == "SECOND"
    assert second["cache_hit"] and model.calls == 1
    assert second["usage"] == {"input_tokens": 0, "output_tokens": 0}


@pytest.mark.parametrize("field,value", [("provider", "openai"), ("thinking", True)])
def test_cache_isolates_provider_and_generation_configuration(field, value):
    model = Model(draft())
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    agent.assist(context(), "核对一下情况", "NEW")
    setattr(model, field, value)
    assert not agent.assist(context(), "核对一下情况", "NEW")["cache_hit"]
    assert model.calls == 2


def test_cache_value_cannot_be_mutated_by_caller():
    cache = SmartCache()
    source = {"checks": [{"status": "supported"}], "ids": ["O1"]}
    expected = copy.deepcopy(source)
    cache.set("x", source)
    source["ids"].append("O2")
    retrieved = cache.get("x")
    retrieved["checks"][0]["status"] = "unsupported"
    assert cache.get("x") == expected


@pytest.mark.parametrize("reply", [
    "气味差异可能是批次或包装原因。",
    "这可能是由于运输过程中的环境因素导致。",
    "颜色不同是由于批次差异。",
    "运输温度造成气味变化，属于正常情况。",
])
def test_unverified_authenticity_explanations_are_repaired(reply):
    message = "眼影气味和专柜不一样，担心真假"
    result = review_guidance(draft(suggested_reply=reply), context(), message,
                             service_focus(message, "authenticity_check"))
    assert any(issue["code"] == "batch_explanation_not_verified" for issue in result["issues"])
    assert result["changes"]["suggested_reply"] != reply


@pytest.mark.parametrize("reply", [
    "泵头问题可能是运输导致，请先检查。",
    "瓶身破损是由于包装原因。",
])
def test_damage_cause_is_not_guessed(reply):
    message = "泵头按不出来"
    result = review_guidance(draft(suggested_reply=reply), context(), message,
                             service_focus(message, "quality_issue"))
    assert any(issue["code"] == "damage_cause_not_verified" for issue in result["issues"])


@pytest.mark.parametrize("reply", [
    "目前不能确认是否是由于批次差异，需要先核查。",
    "需要核实是否由于运输造成破损，再协商售后。",
    "需要核对商品批次与渠道依据，再反馈结果。",
])
def test_uncertainty_or_investigation_is_not_treated_as_cause_assertion(reply):
    message = "眼影气味和专柜不一样"
    result = review_guidance(draft(suggested_reply=reply), context(), message,
                             service_focus(message, "authenticity_check"))
    assert "batch_explanation_not_verified" not in [issue["code"] for issue in result["issues"]]


def test_removed_unknown_citation_has_visible_adjustment_provenance():
    model = Model(draft(evidence_ids=["ORDER-X", "UNKNOWN"]))
    result = AssistAgent(model, NoKnowledge()).assist(context(), "咨询一下", "NEW")
    assert "UNKNOWN" not in result["evidence_ids"]
    assert any("unknown_evidence_removed" in item["reasons"] for item in result["quality_adjustments"])


@pytest.mark.parametrize("reply", [
    "您现在的情况还好吗？需要人工了解处理诉求，已提供的使用信息可以继续核对。",
    "请告诉我们您当前的情况，需要人工优先跟进。",
    "您提到的这些症状现在是否有所变化？需要先核实。",
])
def test_natural_current_condition_questions_pass_without_keyword_rewrite(reply):
    message = "用了精华以后全脸发红，起了小疹子"
    result = review_guidance(draft(suggested_reply=reply), context(), message,
                             service_focus(message, "allergy_reaction"))
    assert "current_condition_not_addressed" not in [issue["code"] for issue in result["issues"]]
