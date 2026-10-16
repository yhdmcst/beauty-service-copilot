from src.knowledge.service_state import build_service_state
from src.agents.assist_agent import AssistAgent
from tests.test_service_guidance import Model, NoKnowledge, context, draft


def row(mid, text, time="2026-06-08 10:00:00", **extra):
    return {"message_id": mid, "message_text": text, "角色": "买家", "发送时间": time, **extra}


def test_pause_and_new_issue_preserve_changes_and_original_sources():
    ctx = context()
    ctx["messages"] = [row("1", "我要退款"), row("2", "先别退款，帮查物流", "2026-06-08 10:01:00")]
    state = build_service_state(ctx, "收到后发现瓶身漏液", "S1")
    assert any(item["intent"] == "refund_request" and item["status"] == "deferred" for item in state["issues"])
    assert any(item["intent"] == "quality_issue" and item["status"] == "active" for item in state["issues"])
    assert state["transitions"][0]["from"] == "active"
    assert state["transitions"][0]["basis"]["message_id"] == "2"


def test_future_staff_unknown_identity_and_undated_messages_are_excluded():
    ctx = context()
    ctx["messages"] = [row("future", "我要退款", "2026-06-09 10:00:00"),
                       row("staff", "我要退款", 角色="客服"), row("undated", "我要退款", ""),
                       row("other", "我要退款", session_id="OTHER")]
    ctx["service_history"] = {"identity_basis": "unconfirmed", "messages": [row("peer", "我要退款", session_id="PEER")]}
    assert build_service_state(ctx, "你好", "S1")["issues"] == []


def test_one_open_issue_can_support_short_followup_without_inventing_status():
    ctx = context(); ctx["messages"] = [row("1", "退款没到账")]
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    result = agent.assist(ctx, "进度怎么样了", "S1")
    assert result["intent"] == "refund_request"
    assert result["service_focus"]["category"] == "refund_status_or_amount"
    assert result["service_state"]["inherited_issue"]["basis"]["message_id"] == "1"


def test_multiple_open_issues_do_not_guess_which_one_followup_means():
    ctx = context(); ctx["messages"] = [row("1", "退款和发票都帮我查")]
    assert build_service_state(ctx, "进度怎么样", "S1")["inherited_issue"] is None


def test_resolution_is_buyer_reported_and_does_not_read_later_state():
    ctx = context(); ctx["messages"] = [row("1", "退款没到账")]
    state = build_service_state(ctx, "退款已经到账", "S1")
    assert state["issues"][0]["status"] == "buyer_reported_resolved"
    assert state["open_count"] == 0
    ctx["analysis_at"] = "2026-06-08 09:00:00"
    assert build_service_state(ctx, "你好", "S1")["issues"] == []


def test_snapshot_local_turns_are_separate_from_historical_replay():
    ctx = context(); ctx["session_id"] = "S1"; ctx["analysis_mode"] = "snapshot"
    ctx["runtime_inputs"] = [row("local", "退款没到账", "2026-10-15T10:00:00+08:00",
                                 session_id="S1", analysis_point=ctx["analysis_point"])]
    state = build_service_state(ctx, "进度怎么样", "S1")
    assert state["inherited_issue"]["intent"] == "refund_request"
    assert state["inherited_issue"]["basis"]["scope"] == "local_snapshot_input"
    ctx["analysis_mode"] = "replay"
    assert build_service_state(ctx, "进度怎么样", "S1")["inherited_issue"] is None


def test_cached_reply_is_invalidated_when_local_turn_state_changes():
    ctx = context(); ctx["session_id"] = "S1"; ctx["analysis_mode"] = "snapshot"
    model = Model(draft()); agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    first = agent.assist(ctx, "进度怎么样", "S1")
    ctx["runtime_inputs"] = [row("local", "退款没到账", session_id="S1", analysis_point=ctx["analysis_point"])]
    second = agent.assist(ctx, "进度怎么样", "S1")
    assert not second["cache_hit"] and model.calls == 2
    assert first["service_state"]["inherited_issue"] is None
    assert second["service_state"]["inherited_issue"]["intent"] == "refund_request"


def test_local_followup_retains_safety_signal_but_replay_does_not_import_it():
    ctx = context(); ctx["session_id"] = "S1"; ctx["analysis_mode"] = "snapshot"
    ctx["runtime_inputs"] = [row("local", "用了之后全脸发红", session_id="S1", analysis_point=ctx["analysis_point"])]
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    assert agent.inspect(ctx, "怎么样了", "S1", "A")["risk_level_rule"] == "critical"
    ctx["analysis_mode"] = "replay"
    assert not any(item.get("scope") == "local_snapshot_input_not_historical_fact"
                   for item in agent.inspect(ctx, "怎么样了", "S1", "A")["rule_alerts"])


def test_outcome_only_refund_links_one_local_issue():
    ctx = context(); ctx["messages"] = [row("1", "我要退款")]
    state = build_service_state(ctx, "已经到账了，谢谢", "S1")
    assert state["open_count"] == 0
    assert state["issues"][0]["status"] == "buyer_reported_resolved"


def test_order_alias_reuses_issue_id_without_backend_binding():
    ctx = context(); ctx["messages"] = [row("1", "订单12345退款")]
    first = build_service_state(ctx, "你好", "S1")
    state = build_service_state(ctx, "这单退款已经到账", "S1")
    assert len(state["issues"]) == 1 and state["open_count"] == 0
    assert state["issues"][0]["issue_id"] == first["issues"][0]["issue_id"]
    assert state["issues"][0]["binding_status"] == "unverified"


def test_partial_quality_resolution_leaves_pump_open():
    ctx = context(); ctx["messages"] = [row("1", "瓶身漏液"), row("2", "泵头也坏了")]
    state = build_service_state(ctx, "漏液已经解决了，泵头还是坏的", "S1")
    issues = {item["detail"]: item for item in state["issues"]}
    assert issues["leak"]["status"] == "buyer_reported_resolved"
    assert issues["pump"]["status"] == "active" and state["open_count"] == 1


def test_receipt_updates_logistics_but_not_damage():
    ctx = context(); ctx["messages"] = [row("1", "帮查物流")]
    state = build_service_state(ctx, "已收到货，但瓶身漏液", "S1")
    assert state["open_count"] == 1
    assert next(x for x in state["issues"] if x["intent"] == "logistics_query")["status"] == "buyer_reported_resolved"


def test_ambiguous_outcome_never_closes_two_orders():
    ctx = context(); ctx["messages"] = [row("1", "订单12345退款，订单67890退款")]
    state = build_service_state(ctx, "已经到账了，谢谢", "S1")
    assert state["open_count"] == 2 and state["review_reasons"]


def test_open_invoice_does_not_survive_explicit_postponement():
    ctx = context(); ctx["messages"] = [row("1", "帮开票")]
    state = build_service_state(ctx, "暂时不要开票", "S1")
    assert state["open_count"] == 0 and state["issues"][0]["status"] == "deferred"
