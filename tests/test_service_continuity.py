"""Adversarial engineering cases; these are not independent human labels."""

import json

import pytest

from src.agents.assist_agent import AssistAgent
from src.knowledge.communication_brief import communication_brief
from src.knowledge.provided_information import supplied_information
from src.knowledge.response_plan import response_plan
from src.knowledge.service_guidance import review_guidance, service_focus
from src.knowledge.service_state import build_service_state
from src.ops.case_store import CaseStore
from src.utils.service_requests import request_plan
from tests.test_service_guidance import Model, NoKnowledge, context, draft
from tests.test_service_state import row


@pytest.mark.parametrize("text", ["退款预计到账", "客服说退款已经到账", "如果退款到账了再说", "退款已经退回仓库"])
def test_forecast_third_party_and_returned_goods_do_not_close_refund(text):
    ctx = context(); ctx["messages"] = [row("1", "我要退款")]
    state = build_service_state(ctx, text, "S1")
    assert state["open_count"] == 1
    assert not any(x["status"] == "buyer_reported_resolved" for x in state["issues"])


@pytest.mark.parametrize("connector", ["，", "但是", "不过", "但"])
def test_clause_resolution_does_not_close_other_defect(connector):
    ctx = context(); ctx["messages"] = [row("1", "瓶身漏液，泵头坏了")]
    state = build_service_state(ctx, f"漏液已经解决了{connector}泵头还是坏的", "S1")
    issues = {x["detail"]: x for x in state["issues"]}
    assert issues["leak"]["status"] == "buyer_reported_resolved"
    assert issues["pump"]["status"] == "active" and state["open_count"] == 1


def test_receipt_is_not_blocked_by_unrelated_negative_clause():
    ctx = context(); ctx["messages"] = [row("1", "查物流")]
    state = build_service_state(ctx, "已收到货，但泵头还没修好", "S1")
    assert next(x for x in state["issues"] if x["intent"] == "logistics_query")["status"] == "buyer_reported_resolved"
    assert state["open_count"] == 1


def test_resolved_request_matches_state_and_preserves_partial_refund():
    plan = request_plan("漏液已经解决了但泵头还是坏的")
    assert [x["status"] for x in plan["items"]] == ["buyer_reported_resolved", "active"]
    ctx = context(); ctx["messages"] = [row("1", "我要退款")]
    state = build_service_state(ctx, "退款已经到账，但还少18元", "S1")
    assert state["open_count"] == 1
    state = build_service_state(ctx, "退款已经到账泵头坏了", "S1")
    assert next(x for x in state["issues"] if x["intent"] == "quality_issue")["status"] == "active"


def test_explicit_other_order_outcome_does_not_close_known_refund():
    ctx = context(); ctx["messages"] = [row("1", "订单12345退款")]
    state = build_service_state(ctx, "订单67890已经到账了", "S1")
    assert state["issues"][0]["status"] == "active"


def test_cancellation_and_reapplication_keep_same_issue_and_event_id():
    ctx = context(); ctx["messages"] = [row("1", "我要退款"), row("2", "取消退款")]
    state = build_service_state(ctx, "现在还是要退款", "S1")
    assert state["open_count"] == 1
    assert [(x["from"], x["to"]) for x in state["transitions"]] == [("active", "cancelled"), ("cancelled", "active")]
    assert all(x["issue_id"] == state["issues"][0]["issue_id"] for x in state["transitions"])
    assert request_plan("撤销开票")["items"][0]["status"] == "cancelled"


def runtime_context():
    ctx = context(); ctx.update(session_id="S1", analysis_mode="snapshot")
    ctx["runtime_inputs"] = [row("LOCAL", "我是敏感肌，照片已经提供", session_id="S1", analysis_point=ctx["analysis_point"])]
    return ctx


def test_runtime_materials_and_preferences_reach_prompt_without_file_confirmation():
    ctx = runtime_context()
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    signals = agent.inspect(ctx, "泵头坏了", "S1", "A")
    items = signals["communication_brief"]["provided_information"]
    material = next(x for x in items if x["kind"] == "reported_material")
    assert material["basis"]["message_id"] == "LOCAL"
    assert material["basis"]["scope"] == "local_snapshot_input"
    assert material["status"] == "buyer_reported_upload_unverified"
    assert signals["communication_brief"]["stated_preferences"][0]["value"] == "敏感肌"
    assert signals["response_plan"]["followup_candidates"] == []
    assert signals["response_plan"]["staff_checks"]
    prompt = agent.build_prompt(ctx, "泵头坏了", "S1", signals)
    assert "先核已有材料" in prompt
    review = review_guidance(draft(suggested_reply="等了这么久很不方便。请您提供照片。"), ctx,
                             "泵头坏了", service_focus("泵头坏了", "quality_issue"))
    assert "等了这么久很不方便" in review["changes"]["suggested_reply"]
    assert "先核材料是否收到" in review["changes"]["suggested_reply"]


@pytest.mark.parametrize("mode,session,point", [("replay", "S1", "buyer-1"), ("snapshot", "OTHER", "buyer-1"), ("snapshot", "S1", "OTHER")])
def test_runtime_materials_do_not_cross_replay_identity_or_point(mode, session, point):
    ctx = runtime_context(); ctx["analysis_mode"] = mode
    ctx["runtime_inputs"][0].update(session_id=session, analysis_point=point)
    assert not any(x["kind"] == "reported_material" for x in supplied_information(ctx, "查退款", "S1"))
    brief = communication_brief(ctx, "查退款", {"session_id": "S1"})
    assert brief["stated_preferences"] == []


def test_missing_time_does_not_become_reusable_history():
    ctx = context(); ctx["messages"] = [row("UNKNOWN", "我是油皮，照片已经提供", time="")]
    assert not any(x["kind"] in {"reported_material", "skin_type"} for x in supplied_information(ctx, "查退款", "S1"))
    assert communication_brief(ctx, "查退款", {"session_id": "S1"})["stated_preferences"] == []


def test_runtime_material_correction_remains_visible_on_followup():
    ctx = runtime_context()
    ctx["runtime_inputs"].append(row("CORRECTION", "照片还没发，之前说错了", session_id="S1", analysis_point=ctx["analysis_point"]))
    items = supplied_information(ctx, "泵头怎么处理", "S1")
    material = next(x for x in items if x["kind"] == "reported_material")
    assert material["status"] == "current_report_conflicts_with_prior_upload"
    assert material["conflict_basis"]["message_id"] == "CORRECTION"
    ctx["runtime_inputs"].append(row("SENT", "照片已经提供", session_id="S1", analysis_point=ctx["analysis_point"]))
    material = next(x for x in supplied_information(ctx, "泵头怎么处理", "S1") if x["kind"] == "reported_material")
    assert material["status"] == "buyer_reported_upload_unverified"
    assert material["basis"]["message_id"] == "SENT"


def test_followup_has_path_reason_and_safety_precedes_order_question():
    ctx = context()
    plan = response_plan(ctx, "泵头坏了", {"session_id": "S1", "intent": "quality_issue", "service_focus": {"category": "product_usability_or_damage"}})
    assert len(plan["followup_candidates"]) == 1
    assert plan["followup_candidates"][0]["field"] == "product_material"
    assert plan["followup_candidates"][0]["reason"]
    ctx["evidence"] = []
    plan = response_plan(ctx, "用后不适", {"session_id": "S1", "intent": "allergy_reaction", "service_focus": {"category": "adverse_reaction_report"}})
    assert plan["followup_candidates"][0]["field"] == "current_condition"


def test_omitted_condition_is_appended_without_erasing_empathy():
    original = draft(suggested_reply="反复说明这些让您很疲惫。建议先停用相关产品。请问您是否已联系客服？")
    result = review_guidance(original, context(), "用后不适", {"category": "adverse_reaction_report"})
    reply = result["changes"]["suggested_reply"]
    assert "反复说明这些让您很疲惫" in reply and "先停用" in reply
    assert "是否已联系客服" not in reply and "当前状况" in reply


def test_repeated_risk_retains_analysis_links_across_restart(tmp_path):
    path = tmp_path / "tasks.sqlite"
    store = CaseStore(path)
    first = store.create_task("S1", "复核", analysis_id="A1", risk_code="repeat")
    second = store.create_task("S1", "复核", analysis_id="A2", risk_code="repeat")
    assert first["task_id"] == second["task_id"]
    store.create_task("S1", "复核", analysis_id="A2", risk_code="repeat")
    assert len(store.get_task(first["task_id"])["analysis_ids"]) == 2
    store.update_task(first["task_id"], "in_progress", owner="测试", waiting_on="仓库")
    updated = store.update_task(first["task_id"], "in_progress", due_at="2026-12-01T00:00:00Z")
    assert "等待：仓库" in next(x["note"] for x in reversed(updated["history"]) if x["action"] == "scheduled")
    store.close()
    reopened = CaseStore(path)
    assert reopened.get_task(first["task_id"])["analysis_ids"] == ["A1", "A2"]
    reopened.close()
