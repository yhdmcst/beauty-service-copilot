"""Contest-data and human-assist workbench integration tests."""

from pathlib import Path
import re
import json
from types import SimpleNamespace

from src.agents.assist_agent import AssistAgent
from src.api.app_upgraded import create_app
from src.data.contest_data import ContestDataStore

ROOT = Path(__file__).resolve().parents[1]


class FakeAssistModel:
    """Deterministic model substitute for API contract tests."""

    def generate_with_usage(self, prompt: str, max_tokens: int = 420):
        prompt_data = json.loads(prompt.split("\n", 2)[2].split("\n\n请严格", 1)[0])
        ids = [
            item["id"] for item in prompt_data["context"]["evidence"]
            if item.get("id")
        ]
        evidence_ids = ids[:2]
        return SimpleNamespace(
            text=json.dumps({
                "summary": "关联订单和工单待人工核对",
                "emotion": "焦急",
                "risk_level": "中",
                "evidence_ids": evidence_ids,
                "missing_info": ["确认最新处理状态"],
                "suggested_reply": "理解您的着急，我们已整理当前订单和工单记录，客服会先核对最新状态后回复您。",
                "next_action": "人工核对订单和工单",
            }, ensure_ascii=False),
            input_tokens=100,
            output_tokens=40,
            model="fake",
        )


def make_app():
    """Build the workbench with imported contest data and a deterministic assistant."""
    store = ContestDataStore(ROOT / "data" / "contest")
    return create_app(contest_store=store, assist_agent=AssistAgent(FakeAssistModel()))


def test_contest_snapshot_contains_cross_source_context():
    store = ContestDataStore(ROOT / "data" / "contest")
    sessions = store.list_sessions()
    assert len(sessions) == 138
    rich = next(item for item in sessions if item["has_order"] and item["has_ticket"])
    detail = store.get_session(rich["session_id"])
    assert detail["orders"] and detail["tickets"]
    assert detail["evidence"]
    assert "赛题提供的虚构 MOCK 数据" in store.context_text(rich["session_id"])


def test_workbench_assist_and_human_task_flow():
    app = make_app()
    client = app.test_client()
    session = next(
        item for item in app.extensions["contest_store"].list_sessions()
        if item["has_order"] and item["has_ticket"]
    )
    session_id = session["session_id"]

    assert client.get("/workbench").status_code == 200
    assert client.get("/api/sessions").status_code == 200
    detail = client.get(f"/api/sessions/{session_id}").get_json()
    assert detail["orders"] and detail["tickets"]

    assist = client.post(
        f"/api/sessions/{session_id}/assist",
        json={"message": detail["latest_buyer_message"]},
    )
    assert assist.status_code == 200
    assert assist.json["model_status"] == "local_qwen"
    assert assist.json["evidence_ids"]

    created = client.post(
        "/api/tasks",
        json={
            "session_id": session_id,
            "task_type": assist.json["next_action"],
            "note": assist.json["summary"],
        },
    )
    assert created.status_code == 201
    task_id = created.json["task"]["task_id"]
    updated = client.patch(
        f"/api/tasks/{task_id}",
        json={"status": "in_progress"},
    )
    assert updated.status_code == 200
    assert client.get(f"/api/tasks?session_id={session_id}").json["tasks"]


def test_risk_negation_and_reaction_boundary():
    from src.risk.beauty_risk_rules import detect_risks

    assert detect_risks("会不会过敏？") == []
    assert detect_risks("用了面霜后脸发红发痒")[0]["level"] == "critical"
    assert detect_risks("没有投诉，只是想问物流") == []


def test_workbench_assist_fails_closed_with_unknown_evidence():
    app = make_app()
    client = app.test_client()
    session_id = app.extensions["contest_store"].list_sessions()[0]["session_id"]
    response = client.post(
        f"/api/sessions/{session_id}/assist",
        json={"message": "测试"},
    )
    assert response.status_code == 200
    assert all(
        evidence_id in {
            item["id"]
            for item in app.extensions["contest_store"].get_session(session_id)["evidence"]
        }
        for evidence_id in response.json["evidence_ids"]
    )


def test_dashboard_demo_uses_the_same_async_workbench_path():
    app = make_app()
    client = app.test_client()
    session = next(
        item for item in app.extensions["contest_store"].list_sessions()
        if item["has_order"] and item["has_ticket"]
    )
    page = client.get("/dashboard")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="demo-session"' in html
    assert "risk_alerts.js" in html
    dashboard_script = (
        ROOT / "frontend" / "static" / "js" / "risk_alerts.js"
    ).read_text(encoding="utf-8")
    assert "/api/sessions/" in dashboard_script
    assert "assist-jobs" in dashboard_script
    assert 'fetch("/chat"' not in dashboard_script

    submitted = client.post(
        f"/api/sessions/{session['session_id']}/assist-jobs",
        json={"message": "请核对当前订单和售后记录", "mode": "snapshot"},
    )
    assert submitted.status_code == 202
    job_id = submitted.json["job"]["job_id"]
    job = app.extensions["analysis_jobs"].get(job_id)
    assert job["session_id"] == session["session_id"]
    app.extensions["analysis_jobs"].close()
