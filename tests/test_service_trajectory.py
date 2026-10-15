"""Temporal, identity-safe service fusion and risk provenance."""

import json
from pathlib import Path

import pytest

from src.agents.assist_agent import AssistAgent
from src.agents.emotion_agent import EmotionAgent
from src.api.app_upgraded import create_app
from src.data.contest_data import ContestDataStore
from src.ops.case_store import CaseStore
from src.orchestration.workbench_workflow import WorkbenchWorkflow
from tests.test_workbench_v2 import Model

ROOT = Path(__file__).resolve().parents[1]


def write_table(directory, name, rows):
    (directory / name).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def service_data(tmp_path):
    chats = []
    for session, date, messages in [
        ("OLD", "2026-05-01", ["您好", "请看一下订单"]),
        ("CURRENT", "2026-05-05", ["谢谢，喜欢", "用了没效果，失望，要投诉"]),
        ("FUTURE", "2026-05-20", ["未来问题"]),
        ("OTHER", "2026-05-02", ["不同消费者"]),
    ]:
        for i, message in enumerate(messages):
            chats.append({
                "会话ID": session, "message_id": f"{session}-{i}",
                "角色": "买家", "消息序号": str(i + 1),
                "发送时间": f"{date} 10:0{i}:00",
                "买家昵称": "同**" if session != "OTHER" else "另**",
                "message_text": message, "内容类型": "文本",
                "scene_major": "售后退货", "scene_minor": "测试场景",
            })
    write_table(tmp_path, "聊天记录.json", chats)
    write_table(tmp_path, "订单.json", [
        {"会话ID": "OLD", "订单号": "O-OLD", "商品名称": "测试精华",
         "下单时间": "2026-04-30 10:00:00", "订单状态": "交易成功"},
        {"会话ID": "CURRENT", "订单号": "O-CURRENT", "商品名称": "测试面霜",
         "下单时间": "2026-05-04 10:00:00", "订单状态": "已发货"},
    ])
    write_table(tmp_path, "线下打款工单.json", [
        {"会话ID": "OLD", "工单号": "R-OLD", "创建时间": "2026-05-01 10:00:00",
         "关联订单号": "O-OLD", "转账状态": "成功", "退款金额(元)": "5"},
        {"会话ID": "CURRENT", "工单号": "R-NOW", "创建时间": "2026-05-05 10:00:00",
         "关联订单号": "O-CURRENT", "转账状态": "待审核", "退款金额(元)": "8"},
        {"会话ID": "CURRENT", "工单号": "R-FUTURE", "创建时间": "2026-05-20 10:00:00",
         "转账状态": "成功", "退款金额(元)": "10"},
    ])
    return ContestDataStore(tmp_path)


def test_masked_names_are_candidates_not_identity(service_data):
    cases = CaseStore()
    context = service_data.with_service_history(
        service_data.get_session("CURRENT"), cases.consumer_identity("CURRENT"))
    history = context["service_history"]
    assert history["identity_basis"] == "unconfirmed"
    assert [row["session_id"] for row in history["candidate_sessions"]] == ["OLD"]
    assert history["messages"] == []
    assert all(item["id"] != "O-OLD" for item in context["evidence"])
    assert len(history["contacts_7d"]) == 1
    assert len(history["refund_records_30d"]) == 1
    assert "OLD" not in json.dumps(service_data.model_context(context))


def test_confirmed_history_fuses_actual_past_records(service_data):
    cases = CaseStore()
    cases.link_sessions("CURRENT", "OLD", "测试复核员", "测试夹具明确设定为同一消费者")
    context = service_data.with_service_history(
        service_data.get_session("CURRENT", analysis_mode="replay"),
        cases.consumer_identity("CURRENT"))
    history = context["service_history"]
    assert len(history["contacts_7d"]) == 2
    assert {row["ticket_id"] for row in history["refund_records_30d"]} == {"R-OLD", "R-NOW"}
    assert any(item["id"] == "O-OLD" for item in context["evidence"])
    assert all(row["发送时间"] <= context["analysis_at"] for row in history["messages"])
    assert "R-FUTURE" not in json.dumps(service_data.model_context(context))


def test_even_confirmed_future_session_does_not_leak(service_data):
    cases = CaseStore()
    cases.link_sessions("CURRENT", "FUTURE", "测试复核员", "明确测试未来会话隔离")
    context = service_data.with_service_history(
        service_data.get_session("CURRENT", analysis_mode="replay"),
        cases.consumer_identity("CURRENT"),
    )
    assert context["service_history"]["messages"] == []
    assert len(context["service_history"]["contacts_7d"]) == 1
    assert "未来问题" not in json.dumps(service_data.model_context(context), ensure_ascii=False)


def test_distinct_sessions_not_message_count(service_data):
    cases = CaseStore()
    context = service_data.with_service_history(
        service_data.get_session("CURRENT"), cases.consumer_identity("CURRENT"))
    signals = AssistAgent(Model()).inspect(context, "查一下订单", "CURRENT", "A1")
    assert signals["service_risk_counts"]["contacts_7d"] == 1
    assert "repeat_contact" not in {item["code"] for item in signals["rule_alerts"]}


def test_repeat_risk_has_sources_and_no_completed_refund_claim(service_data):
    cases = CaseStore()
    cases.link_sessions("CURRENT", "OLD", "测试复核员", "明确测试同一消费者")
    flow = WorkbenchWorkflow(service_data, AssistAgent(Model()), cases, lambda event: None)
    result = flow.run("CURRENT", "查一下订单")
    alerts = {item["code"]: item for item in result["rule_alerts"]}
    assert set(alerts["repeat_contact"]["source_session_ids"]) == {"OLD", "CURRENT"}
    assert set(alerts["repeat_refund_records"]["source_ticket_ids"]) == {"R-OLD", "R-NOW"}
    assert result["service_risk_counts"]["refund_completion_count"] is None
    assert result["risk_level"] in {"高", "紧急"}
    first_ids = {task["task_id"] for task in cases.list_tasks()}
    flow.run("CURRENT", "查一下订单")
    assert {task["task_id"] for task in cases.list_tasks()} == first_ids


def test_emotion_escalation_uses_past_buyer_messages(service_data):
    cases = CaseStore()
    context = service_data.with_service_history(
        service_data.get_session("CURRENT"), cases.consumer_identity("CURRENT"))
    agent = AssistAgent(Model())
    signals = agent.inspect(context, context["latest_buyer_message"], "CURRENT", "A1")
    assert signals["emotion_trend"]["trend"] == "升级"
    assert signals["emotion_trend"]["history"][0]["message_id"] == "CURRENT-0"
    assert "emotion_escalation" in {alert["code"] for alert in signals["rule_alerts"]}
    point_context = service_data.get_session("CURRENT", before_message_id="CURRENT-0")
    point_signals = agent.inspect(point_context, point_context["latest_buyer_message"], "CURRENT", "A2")
    assert point_signals["emotion_trend"]["history"] == []


def test_identity_link_persistence_and_conflicting_groups(tmp_path):
    path = tmp_path / "identity.sqlite"
    store = CaseStore(path)
    with pytest.raises(ValueError):
        store.link_sessions("S1", "S2", "", "reason")
    with pytest.raises(ValueError):
        store.link_sessions("S1", "S2", "reviewer", "")
    store.link_sessions("S1", "S2", "测试复核员", "仅测试关系")
    store.link_sessions("S3", "S4", "测试复核员", "另一个消费者")
    with pytest.raises(ValueError):
        store.link_sessions("S1", "S3", "测试复核员", "拒绝静默合并两组")
    store.close()
    reopened = CaseStore(path)
    assert set(reopened.consumer_identity("S1")["sessions"]) == {"S1", "S2"}
    assert reopened.consumer_identity("S1")["confirmations"][0]["reason"]
    reopened.close()


def test_identity_api_requires_real_sessions_and_explicit_fields(service_data):
    app = create_app(contest_store=service_data, assist_agent=AssistAgent(Model()), case_store=CaseStore())
    client = app.test_client()
    assert client.post("/api/sessions/CURRENT/link", json={"other_session_id": "OLD"}).status_code == 400
    assert client.post("/api/sessions/CURRENT/link", json={
        "other_session_id": "UNKNOWN", "reviewer": "test", "reason": "fixture",
    }).status_code == 404
    response = client.post("/api/sessions/CURRENT/link", json={
        "other_session_id": "OLD", "reviewer": "自动化夹具", "reason": "夹具中明确同一消费者",
    })
    assert response.status_code == 201
    assert client.get("/api/sessions/CURRENT").json["service_history"]["identity_basis"] != "unconfirmed"
    analysis = client.post("/api/sessions/CURRENT/assist", json={"message": "查看退款"}).json
    assert analysis["service_risk_counts"]["refund_records_30d"] == 2


@pytest.mark.parametrize("text,negative", [
    ("没有投诉，只是查物流", False),
    ("已经不过敏了，也没有红肿", False),
    ("用了没效果，很失望", True),
])
def test_current_emotion_negation_is_not_keyword_only(text, negative):
    emotion = EmotionAgent().analyze(text)
    assert (emotion["valence"] < -0.5) is negative


@pytest.mark.parametrize("session_id,expected_level,expected_code", [
    ("S00154", "high", "structured_adverse_reaction"),
    ("S00082", "critical", "structured_adverse_reaction"),
    ("S00024", "high", "structured_after_sales_risk"),
])
def test_historical_and_structured_risk_cannot_be_cleared_by_polite_last_message(
    session_id, expected_level, expected_code,
):
    store = ContestDataStore(ROOT / "data" / "contest")
    context = store.get_session(session_id)
    context = store.with_service_history(context, CaseStore().consumer_identity(session_id))
    signals = AssistAgent(Model()).inspect(
        context, context["latest_buyer_message"], session_id, "risk-history",
    )
    assert signals["risk_level_rule"] == expected_level
    assert expected_code in {item["code"] for item in signals["rule_alerts"]}
