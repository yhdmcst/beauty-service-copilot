"""Focused tests for persistent human review, temporal evidence and actual Agent flow."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agents.assist_agent import AssistAgent, FALLBACK_REPLY
from src.api.app_upgraded import create_app
from src.data.contest_data import ContestDataStore
from src.ops.case_store import CaseStore
from src.orchestration.workbench_workflow import WorkbenchWorkflow
from src.risk.beauty_risk_rules import detect_risks

ROOT = Path(__file__).resolve().parents[1]


class Model:
    """No live model calls in regression tests."""

    model = "fixture-model"
    provider = "ollama"

    def __init__(self, failing=False, bad_schema=False):
        self.calls = 0
        self.prompts = []
        self.failing = failing
        self.bad_schema = bad_schema

    def generate_with_usage(self, prompt, max_tokens=420):
        self.calls += 1
        self.prompts.append(prompt)
        if self.failing:
            raise TimeoutError("fixture timeout")
        data = json.loads(prompt.split("\n", 2)[2].split("\n\n请严格", 1)[0])
        ids = [item["id"] for item in data["context"]["evidence"]]
        draft = {
            "summary": "客户咨询物流，需要核对业务记录。",
            "emotion": "中性", "risk_level": "低", "evidence_ids": ids,
            "missing_info": ["核对最新物流状态"],
            "suggested_reply": "理解您希望及时了解进度，客服会核对当前物流记录，再与您确认。",
            "next_action": "核实物流记录",
        }
        if self.bad_schema:
            draft["evidence_ids"] = "not an array"
        return SimpleNamespace(
            text=json.dumps(draft, ensure_ascii=False), input_tokens=120,
            output_tokens=40, model=self.model,
        )


def data_store():
    return ContestDataStore(ROOT / "data" / "contest")


def app_with(model=None, cases=None):
    return create_app(
        contest_store=data_store(), assist_agent=AssistAgent(model or Model()),
        case_store=cases or CaseStore(),
    )


def analysis_record(id_="A1", session="S1"):
    return {
        "analysis_id": id_, "session_id": session, "suggested_reply": "测试草稿",
        "created_at": "2026-10-04T09:00:00+08:00", "emotion": "中性",
        "intent": "logistics_query", "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def test_task_survives_restart_and_has_audit(tmp_path):
    path = tmp_path / "demo.sqlite"
    first = CaseStore(path)
    task = first.create_task("S1", "人工复核", risk_code="complaint", priority="high")
    second = first.create_task("S1", "人工复核", risk_code="complaint", priority="high")
    assert second["task_id"] == task["task_id"]
    first.update_task(task["task_id"], "in_progress", owner="H227", actor="H227")
    first.close()
    reopened = CaseStore(path)
    assert reopened.get_task(task["task_id"])["owner"] == "H227"
    with pytest.raises(ValueError):
        reopened.update_task(task["task_id"], "resolved")
    resolved = reopened.update_task(task["task_id"], "resolved", "已核实，演示关闭", actor="H227")
    assert len(resolved["history"]) == 3
    with pytest.raises(ValueError):
        reopened.update_task(task["task_id"], "in_progress")
    reopened.close()


def test_task_cannot_skip_claim():
    cases = CaseStore()
    task = cases.create_task("S1", "follow up")
    with pytest.raises(ValueError):
        cases.update_task(task["task_id"], "resolved", "done")


def test_human_reviews_are_persistent_and_not_send_actions(tmp_path):
    path = tmp_path / "reviews.sqlite"
    cases = CaseStore(path)
    cases.record_analysis(analysis_record())
    with pytest.raises(ValueError):
        cases.review("A1", "accepted", "另一回复", "", "H227")
    cases.review("A1", "edited", "核实后回复", "补充实际状态", "H227")
    with pytest.raises(ValueError):
        cases.review("A1", "edited", "又改一次", "", "H227")
    cases.close()
    reopened = CaseStore(path)
    assert reopened.feedback("S1")[0]["decision"] == "edited"
    assert reopened.dashboard()["adoption_rate"] == 1
    reopened.close()


def test_statistics_count_sessions_not_analyses():
    cases = CaseStore()
    cases.record_analysis(analysis_record("A1"))
    cases.record_analysis(analysis_record("A2"))
    task = cases.create_task("S1", "投诉复核", risk_code="complaint", priority="high")
    assert cases.dashboard()["served"] == 1
    assert cases.dashboard()["analysis_count"] == 2
    assert cases.dashboard()["high_risk"] == 1
    cases.update_task(task["task_id"], "in_progress", owner="H227")
    cases.update_task(task["task_id"], "resolved", "核实完毕")
    assert cases.dashboard()["high_risk"] == 0
    assert cases.usage_stats()["cost"]["total_tokens"] == 24


def test_replay_boundaries_and_labels_not_sent():
    store = data_store()
    latest = store.get_session("S00381")
    first = latest["message_choices"][0]["id"]
    bounded = store.get_session("S00381", before_message_id=first, analysis_mode="replay")
    assert bounded["messages"][-1]["message_id"] == first
    assert all(row["发送时间"] <= bounded["analysis_at"] for row in bounded["messages"])
    prompt_data = store.model_context(bounded)
    text = json.dumps(prompt_data, ensure_ascii=False)
    assert "scene_major" not in text and "scene_minor" not in text
    assert "chat_content" not in text and "支付宝账号" not in text
    assert len(prompt_data["messages"]) <= 8
    for record in bounded["orders"] + bounded["tickets"]:
        for key in ("订单状态", "工单状态", "任务状态", "转账状态"):
            if key in record:
                assert record[key] == "历史状态未提供"


def test_analysis_point_validation():
    with pytest.raises(ValueError):
        data_store().get_session("S00381", before_message_id="unknown")
    with pytest.raises(ValueError):
        data_store().get_session("S00381", analysis_mode="unknown")


def test_urgent_task_emitted_before_model_even_when_model_fails():
    cases, events = CaseStore(), []
    model = Model(failing=True)
    flow = WorkbenchWorkflow(data_store(), AssistAgent(model), cases, events.append)
    result = flow.run("S00381", "用了以后红肿，呼吸困难")
    assert result["risk_level"] == "紧急"
    assert result["model_status"] == "rule_safety"
    assert model.calls == 0
    assert events[0]["phase"] == "safety"
    assert cases.list_tasks()[0]["priority"] == "critical"
    assert [node["node"] for node in result["trace"]] == ["evidence", "safety", "draft", "verify", "audit"]
    assert cases.get_analysis(result["analysis_id"])["session_id"] == "S00381"
    assert "医疗帮助" in result["suggested_reply"]


def test_task_list_prioritizes_urgent_risk_over_other_open_alerts():
    cases = CaseStore()
    cases.create_task("S1", "情绪升级", priority="high", risk_code="emotion")
    urgent = cases.create_task("S1", "过敏反应", priority="critical", risk_code="allergy")
    assert cases.list_tasks("S1")[0]["task_id"] == urgent["task_id"]
    assert cases.dashboard()["alerts"][0]["task_id"] == urgent["task_id"]


def test_schema_failure_preserves_measured_usage():
    app = app_with(Model(bad_schema=True))
    response = app.test_client().post("/api/sessions/S00381/assist", json={"message": "查一下物流"})
    assert response.status_code == 200
    assert response.json["model_status"] == "fallback"
    assert response.json["usage"]["input_tokens"] == 120
    assert app.test_client().get("/api/cost").json["cost"]["total_tokens"] == 160


def test_model_cannot_lower_rule_risk_and_cached_repeat_is_not_billed():
    model, cases = Model(), CaseStore()
    app = app_with(model, cases)
    client = app.test_client()
    payload = {"message": "用了脸上发红刺痛"}
    first = client.post("/api/sessions/S00381/assist", json=payload).json
    second = client.post("/api/sessions/S00381/assist", json=payload).json
    assert first["risk_level"] == "紧急" and second["risk_level"] == "紧急"
    assert second["cache_hit"] and model.calls == 1
    assert cases.usage_stats()["cost"]["total_tokens"] == 160
    assert {task["task_id"] for task in cases.list_tasks()} == set(first["task_ids"])
    assert len([task for task in cases.list_tasks() if task["risk_code"] == "allergy"]) == 1


def test_workbench_main_path_runs_knowledge_gate_and_preserves_provenance():
    class KnowledgeFixture:
        def search(self, query, intent):
            return {
                "retrieved_docs": [{
                    "id": "K1", "title": "模拟护肤知识", "source": "模拟样本",
                    "content": "仅供演示", "verified": False,
                }],
                "context": "仅供演示",
                "confidence": 0.0,
                "can_auto_reply": False,
                "reason": "unverified_evidence",
            }

    app = create_app(
        contest_store=data_store(),
        assist_agent=AssistAgent(Model(), knowledge_agent=KnowledgeFixture()),
        case_store=CaseStore(),
    )
    result = app.test_client().post(
        "/api/sessions/S00381/assist",
        json={"message": "敏感肌适合什么护肤？"},
    )
    assert result.status_code == 200
    assert result.json["knowledge"]["reason"] == "unverified_evidence"
    assert result.json["knowledge"]["retrieved_docs"][0]["verified"] is False


def test_review_and_task_api_are_session_bound():
    client = app_with().test_client()
    analysis = client.post("/api/sessions/S00381/assist", json={"message": "查物流"}).json
    feedback = client.post(f"/api/analyses/{analysis['analysis_id']}/review", json={
        "decision": "accepted", "edited_reply": analysis["suggested_reply"], "reviewer": "H227",
    })
    assert feedback.status_code == 201
    assert client.post("/api/tasks", json={
        "session_id": "S00474", "task_type": "review", "analysis_id": analysis["analysis_id"],
    }).status_code == 400
    assert client.post("/api/sessions/S00381/assist", json=["invalid"]).status_code == 400
    assert client.patch("/api/tasks/unknown", json=["bad"]).status_code == 400
    assert client.post("/api/sessions/S00381/assist", json={
        "message": "x" * 2001,
    }).status_code == 400


@pytest.mark.parametrize("text,should_trigger", [
    ("没有投诉，只想查物流", False), ("已经不过敏了，也没有红肿", False),
    ("没效果，脸上红肿刺痛", True), ("没有刺痛，但脸上红肿", True),
    ("会不会过敏", False), ("用了发生过敏了", True),
])
def test_negation_scope(text, should_trigger):
    assert bool(detect_risks(text)) is should_trigger


def test_holdout_template_families_are_disjoint_and_labels_pending():
    from evaluation.prepare_holdout import prepare

    pack = prepare(data_store())
    development = {item["family_for_split_only"] for item in pack["development"]}
    heldout = {item["family_for_split_only"] for item in pack["heldout"]}
    assert not development & heldout
    assert len(pack["development"]) == 20 and len(pack["heldout"]) == 30
    assert all(item["human_annotation"]["status"] == "pending"
               for item in pack["development"] + pack["heldout"])


class MoneyModel(Model):
    def generate_with_usage(self, prompt, max_tokens=420):
        result = super().generate_with_usage(prompt, max_tokens)
        draft = json.loads(result.text)
        draft["suggested_reply"] = "您的订单实付10元。"
        result.text = json.dumps(draft, ensure_ascii=False)
        return result


def test_amount_must_match_exact_cited_business_value_not_substring():
    agent = AssistAgent(MoneyModel())
    context = data_store().get_session("S00381")
    context["evidence"] = [{
        "id": "ORDER1", "label": "订单", "type": "order", "summary": "测试",
        "fields": {"实付金额(元)": "100"},
    }]
    result = agent.assist(context, "金额多少", "S00381")
    assert result["suggested_reply"] == FALLBACK_REPLY
    assert "unsupported_amount" in result["validation_flags"]


def test_workbench_emits_socket_alert_and_links_same_session():
    from src.api.websocket_handler import socketio

    app = app_with()
    client = app.test_client()
    socket = socketio.test_client(app)
    response = client.post("/api/sessions/S00381/assist", json={"message": "要投诉12315"})
    assert response.status_code == 200
    events = socket.get_received()
    assert any(event["name"] == "assist_update" and event["args"][0]["phase"] == "safety"
               for event in events)
    assert client.get("/api/dashboard").json["alerts"][0]["session_id"] == "S00381"
    socket.disconnect()
