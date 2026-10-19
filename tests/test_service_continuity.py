import json
import copy
from types import SimpleNamespace

import pytest

from src.agents.assist_agent import AssistAgent
from src.knowledge.response_plan import response_plan
from src.knowledge.service_guidance import review_guidance, service_focus
from src.knowledge.service_state import build_service_state
from src.utils.service_requests import request_plan, current_request_text
from tests.test_service_guidance import context, draft, Model, NoKnowledge


def test_request_plan_keeps_current_logistics_after_deferred_refund():
    text = "暂时不退款，先查询物流"
    plan = request_plan(text)
    assert "物流" in current_request_text(text)
    assert any(item["intent"] == "logistics_query" and item["status"] == "active"
               for item in plan["items"])
    assert any(item["status"] == "deferred" for item in plan["items"])


def test_request_plan_marks_multiple_orders_for_review():
    plan = request_plan("这单退款，另一单改地址")
    assert plan["requires_review"]
    assert any("不同订单" in reason for reason in plan["review_reasons"])


def test_service_state_closes_only_buyer_reported_single_issue():
    ctx = context()
    ctx["messages"] = [{"角色": "买家", "message_id": "m1",
                        "message_text": "退款没到账", "发送时间": "2026-06-08 10:00:00"}]
    state = build_service_state(ctx, "退款已经到账，谢谢", "S1")
    assert state["open_count"] == 0
    assert state["issues"][0]["status"] == "buyer_reported_resolved"


def test_service_state_keeps_unresolved_issue_for_short_followup():
    ctx = context()
    ctx["messages"] = [{"角色": "买家", "message_id": "m1",
                        "message_text": "退款没到账", "发送时间": "2026-06-08 10:00:00"}]
    state = build_service_state(ctx, "进度怎么样", "S1")
    assert state["open_count"] == 1
    assert state["inherited_issue"]["intent"] == "refund_request"


def test_response_plan_asks_at_most_one_missing_question():
    ctx = context()
    ctx["evidence"] = []
    plan = response_plan(ctx, "退款没到账", {
        "session_id": "S1", "intent": "refund_request",
        "service_focus": {"category": "refund_status_or_amount"},
    })
    assert len(plan["followup_candidates"]) == 1
    assert plan["followup_candidates"][0]["owner"] == "customer_only_if_missing"


def test_local_reply_repair_keeps_empathy_sentence():
    original = draft(
        suggested_reply="等了这么久还没拿到退款，确实让您着急。请您提供退款流水。核对后再向您说明可办理路径。",
        next_action="客服核退款流水及费用明细",
    )
    result = review_guidance(
        original, context(), "退款没到账",
        service_focus("退款没到账", "refund_request"),
    )
    text = result["changes"]["suggested_reply"]
    assert "等了这么久还没拿到退款" in text
    assert "请您提供退款流水" not in text
    assert original["suggested_reply"].startswith("等了这么久")


def test_internal_record_request_in_next_action_is_not_shifted_to_buyer():
    original = draft(
        suggested_reply="退款差额需要查清楚，由客服核对后反馈。",
        next_action="请提供退款流水截图及费用明细，以便我们进一步核查。",
    )
    result = review_guidance(
        original, context(), "退款金额少了12元",
        service_focus("退款金额少了12元", "refund_request"),
    )
    assert "请提供" not in result["changes"]["next_action"]
    assert "客服" in result["changes"]["next_action"]


class _Model:
    model = "fixture"
    provider = "ollama"

    def generate_with_usage(self, prompt, max_tokens=360):
        data = json.loads(prompt.split("\n", 2)[2].split("\n\n请严格", 1)[0])
        evidence_ids = [item["id"] for item in data["context"]["evidence"]]
        return SimpleNamespace(
            text=json.dumps({
                "summary": "买家需要继续核查当前事项。",
                "emotion": "中性",
                "risk_level": "低",
                "evidence_ids": evidence_ids,
                "missing_info": [],
                "suggested_reply": "先核对当前记录，再向您说明。",
                "next_action": "客服核对当前记录后反馈",
            }, ensure_ascii=False),
            input_tokens=100, output_tokens=40, model=self.model,
        )


def test_assistance_exposes_continuity_and_plan_without_extra_model_call():
    agent = AssistAgent(_Model(), NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(context(), "退款没到账", "S1")
    assert "service_state" in result
    assert "response_plan" in result
    assert result["response_plan"]["additional_model_calls"] == 0


def buyer(identifier, text, at="2026-06-08 10:00:00", **extra):
    return {
        "message_id": identifier, "message_text": text,
        "角色": "买家", "发送时间": at, **extra,
    }


def test_state_excludes_future_staff_undated_and_unconfirmed_other_buyers():
    ctx = context()
    ctx["messages"] = [
        buyer("future", "我要退款", at="2026-06-09 10:00:00"),
        buyer("staff", "我要退款", 角色="客服"),
        buyer("undated", "我要退款", at=""),
        buyer("other", "我要退款", session_id="OTHER"),
    ]
    ctx["service_history"] = {
        "identity_basis": "unconfirmed",
        "messages": [buyer("peer", "我要退款", session_id="PEER")],
    }
    previous = copy.deepcopy(ctx)
    assert build_service_state(ctx, "你好", "S1")["issues"] == []
    assert ctx == previous


def test_state_only_reads_explicitly_confirmed_peer_sessions():
    ctx = context()
    ctx["service_history"] = {
        "identity_basis": "human_confirmed",
        "confirmed_session_ids": ["S1", "CONFIRMED"],
        "messages": [
            buyer("good", "退款没到账", session_id="CONFIRMED"),
            buyer("bad", "我要开票", session_id="OTHER"),
        ],
    }
    state = build_service_state(ctx, "进度怎么样", "S1")
    assert len(state["issues"]) == 1
    assert state["issues"][0]["basis"]["session_id"] == "CONFIRMED"
    assert state["inherited_issue"] is None


def test_partial_resolution_keeps_other_product_issue_open():
    ctx = context()
    ctx["messages"] = [buyer("1", "瓶身漏液"), buyer("2", "泵头也坏了")]
    state = build_service_state(ctx, "漏液已经解决了，泵头还是坏的", "S1")
    issues = {item["detail"]: item for item in state["issues"]}
    assert issues["leak"]["status"] == "buyer_reported_resolved"
    assert issues["pump"]["status"] == "active" and state["open_count"] == 1
    assert state["scope"] == "buyer_reported_state_not_backend_confirmation"


@pytest.mark.parametrize("text", [
    "如果到账了再说", "客服说退款已经到账", "退款还没到账",
    "退款到账了吗", "退款到账了但是还少了12元",
    "不是退款已经到账，先别结束", "并非退款到账了",
])
def test_hypothesis_question_staff_claim_or_shortfall_does_not_resolve_refund(text):
    ctx = context()
    ctx["messages"] = [buyer("1", "我要退款")]
    state = build_service_state(ctx, text, "S1")
    assert any(item["status"] == "active" for item in state["issues"])
    assert not any(item["status"] == "buyer_reported_resolved" for item in state["issues"])


def test_receipt_condition_does_not_resolve_logistics():
    ctx = context()
    ctx["messages"] = [buyer("1", "帮查物流")]
    state = build_service_state(ctx, "收到后再确认", "S1")
    assert state["open_count"] == 1
    assert state["issues"][0]["status"] == "active"


def test_return_warehouse_signature_is_not_a_separate_delivery_request():
    message = "我的退货仓库签收了，售后关闭钱退不出来"
    plan = request_plan(message)
    assert not plan["requires_review"]
    assert {item["intent"] for item in plan["items"]} == {"refund_request"}


@pytest.mark.parametrize("text", [
    "之前退货说过会退运费，钱一直没收到",
    "上次退货说好报销运费的，款项还未到账",
    "原来退货时说要报销，运费仍没回来",
])
def test_old_refund_with_unresolved_money_in_next_clause_stays_current(text):
    from src.agents.intent_agent import IntentAgent

    plan = request_plan(text)
    assert any(
        item["intent"] == "refund_request" and item["status"] == "active"
        for item in plan["items"]
    )
    intent = IntentAgent().classify(text)["intent_name"]
    assert intent == "refund_request"
    assert service_focus(text, intent)["category"] == "return_refund"


def test_unpaid_money_on_another_order_does_not_reactivate_old_refund():
    plan = request_plan("上次退货处理完了，另一单的钱还没收到")
    assert plan["items"][0]["status"] == "historical"


def test_plain_request_prompt_is_unchanged_by_ui_only_plans():
    agent = AssistAgent(Model(draft()), NoKnowledge())
    ctx = context()
    message = "泵头坏了，需要核查"
    signals = agent.inspect(ctx, message, "S1", "A1")
    assert signals["response_plan"]["followup_candidates"]
    current = agent.build_prompt(ctx, message, "S1", signals)
    stripped = {
        key: value for key, value in signals.items()
        if key not in {"request_plan", "service_state", "response_plan"}
    }
    assert agent.build_prompt(ctx, message, "S1", stripped) == current


def test_ambiguous_outcome_does_not_close_two_order_issues():
    ctx = context()
    ctx["messages"] = [buyer("1", "订单12345退款，订单67890退款")]
    state = build_service_state(ctx, "已经到账了，谢谢", "S1")
    assert state["open_count"] == 2 and state["review_reasons"]


def test_inherited_focus_survives_model_intent_completion():
    ctx = context()
    ctx["messages"] = [buyer("1", "退货后售后关闭钱退不出来")]
    model = Model({**draft(), "t": "refund_request"})
    result = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False).assist(
        ctx, "进度怎么样", "S1",
    )
    assert result["service_focus"]["category"] == "return_refund"
    assert "售后" in result["next_action"] and "退款" in result["next_action"]
    assert model.calls == 1


def test_single_current_issue_is_not_duplicated_into_prompt_state():
    agent = AssistAgent(Model(draft()), NoKnowledge())
    ctx = context()
    message = "退款没到账"
    signals = agent.inspect(ctx, message, "S1", "A1")
    prompt = agent.build_prompt(ctx, message, "S1", signals)
    payload = json.loads(prompt.split("\n", 2)[2].split("\n\n请严格", 1)[0])
    assert signals["service_state"]["issues"]
    assert "service_state" not in payload
    assert "reply_plan" not in payload


def test_multi_order_reply_is_explicit_about_unverified_binding():
    original = draft()
    result = review_guidance(
        original, context(), "这单退款，另一单改地址",
        service_focus("这单退款，另一单改地址", "refund_request"),
    )
    assert "对应关系" in result["changes"]["suggested_reply"]
    assert "修改成功" not in result["changes"]["suggested_reply"]
    assert "ORDER-X" not in result["changes"]["suggested_reply"]


def test_new_critical_symptom_is_never_lost_in_request_planning():
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(context(), "暂时不退款，但用后全脸发红", "S1")
    assert result["risk_level"] == "紧急"
    assert result["service_focus"]["category"] == "adverse_reaction_report"


def test_snapshot_input_continuity_survives_store_restart_and_retries(tmp_path):
    from src.ops.case_store import CaseStore
    from src.orchestration.workbench_workflow import WorkbenchWorkflow
    from tests.test_workbench_v2 import data_store

    data = data_store()
    sid = "S00014"
    point = data.get_session(sid)["message_choices"][0]["id"]
    path = tmp_path / "isolated.sqlite"
    cases = CaseStore(path)
    model = Model(draft())
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    workflow = WorkbenchWorkflow(data, agent, cases, lambda event: None)
    first = workflow.run(sid, "我要退款", point=point, mode="snapshot")
    repeated = workflow.run(sid, "我要退款", point=point, mode="snapshot")
    assert repeated["cache_hit"] and model.calls == 1
    assert first["input_is_override"]
    cases.close()

    cases = CaseStore(path)
    workflow = WorkbenchWorkflow(data, agent, cases, lambda event: None)
    state = workflow.prepare(sid, "进度怎么样", point, "snapshot")
    assert any(row["message_text"] == "我要退款" for row in state["context"]["runtime_inputs"])
    assert state["signals"]["service_state"]["inherited_issue"]["intent"] == "refund_request"
    replay = workflow.prepare(sid, "进度怎么样", point, "replay")
    assert not replay["context"].get("runtime_inputs")
    cases.close()


def test_snapshot_previous_risk_is_preserved_but_not_imported_into_replay():
    ctx = context()
    ctx.update(session_id="S1", analysis_mode="snapshot")
    ctx["runtime_inputs"] = [buyer(
        "runtime", "用了以后全脸发红", session_id="S1",
        analysis_point=ctx["analysis_point"],
    )]
    agent = AssistAgent(Model(draft()), NoKnowledge())
    snapshot = agent.inspect(ctx, "进度怎么样", "S1", "A1")
    assert snapshot["risk_level_rule"] == "critical"
    ctx["analysis_mode"] = "replay"
    replay = agent.inspect(ctx, "进度怎么样", "S1", "A2")
    assert not any(
        alert.get("scope") == "local_snapshot_input_not_historical_fact"
        for alert in replay["rule_alerts"]
    )


def test_materials_from_local_snapshot_are_reused_without_import_into_replay():
    from src.knowledge.provided_information import supplied_information

    ctx = context()
    ctx.update(session_id="S1", analysis_mode="snapshot")
    ctx["runtime_inputs"] = [buyer(
        "material", "照片已经提供，泵头坏了", session_id="S1",
        analysis_point=ctx["analysis_point"],
    )]
    items = supplied_information(ctx, "进度怎么样", "S1")
    material = next(item for item in items if item["kind"] == "reported_material")
    assert material["status"] == "buyer_reported_upload_unverified"
    assert material["basis"]["message_id"] == "material"
    ctx["analysis_mode"] = "replay"
    assert not any(
        item["kind"] == "reported_material"
        for item in supplied_information(ctx, "进度怎么样", "S1")
    )
