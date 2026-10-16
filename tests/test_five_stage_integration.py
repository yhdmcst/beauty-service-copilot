import sqlite3

import pytest

from src.knowledge.service_guidance import review_guidance, service_focus
from src.knowledge.response_plan import response_plan
from src.ops.case_store import CaseStore
from tests.test_service_guidance import context, draft
from tests.test_workbench_v2 import app_with, analysis_record


def test_sentence_repair_keeps_specific_empathy_and_correct_next_step():
    original = draft(
        suggested_reply="等了这么久还没拿到退款，确实让您着急。请您提供退款流水。核对后再向您说明可办理路径。",
        next_action="客服核退款流水及费用明细",
    )
    result = review_guidance(original, context(), "退款没到账", service_focus("退款没到账", "refund_request"))
    text = result["changes"]["suggested_reply"]
    assert "等了这么久还没拿到退款" in text and "核对后再向您说明可办理路径" in text
    assert "请您提供退款流水" not in text and "由客服核查" in text
    assert "请您提供退款流水" in original["suggested_reply"]


def test_multiple_bad_sentences_repaired_without_erasing_valid_sentence():
    original = draft(suggested_reply="这笔退款让您久等了。请您提供订单号。请您提供退款流水。")
    result = review_guidance(original, context(), "退款没到账", service_focus("退款没到账", "refund_request"))
    text = result["changes"]["suggested_reply"]
    assert "这笔退款让您久等了" in text
    assert "请您提供" not in text
    assert "已有订单" in text and "由客服核查" in text


def test_followup_plan_does_not_request_known_order_or_internal_records():
    result = response_plan(context(), "退款没到账", {"session_id": "S1", "intent": "refund_request",
        "service_focus": {"category": "refund_status_or_amount"}})
    assert result["followup_candidates"] == []
    assert any(item["label"] == "已有订单记录" for item in result["known_information"])


def test_followup_plan_asks_one_key_question_only_if_not_available():
    ctx = context(); ctx["evidence"] = []
    result = response_plan(ctx, "退款没到账", {"session_id": "S1", "intent": "refund_request",
        "service_focus": {"category": "refund_status_or_amount"}})
    assert len(result["followup_candidates"]) == 1
    assert "先查" in result["followup_candidates"][0]["action"]


def test_task_schedule_reopen_restart_and_old_db_migration(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task_type TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL, owner TEXT NOT NULL, priority TEXT NOT NULL, risk_code TEXT NOT NULL, analysis_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.execute("INSERT INTO tasks VALUES ('OLD','S','核查','原记录','pending','','high','risk','','2026-01-01','2026-01-01')")
    db.commit(); db.close()
    store = CaseStore(path)
    assert store.get_task("OLD")["note"] == "原记录"
    assert store.get_task("OLD")["due_at"] == ""
    task = store.update_task("OLD", "in_progress", owner="测试客服", due_at="2020-01-01T12:00:00+08:00", waiting_on="仓库")
    assert task["overdue"] and task["due_at"] == "2020-01-01T04:00:00+00:00"
    store.update_task("OLD", "resolved", "内部核查完成，消费者结果待确认")
    with pytest.raises(ValueError, match="reopen"):
        store.update_task("OLD", "pending")
    task = store.update_task("OLD", "pending", "消费者再次反映未解决")
    assert task["overdue"] and any(event["action"] == "reopened" for event in task["history"])
    store.close()
    reopened = CaseStore(path)
    assert reopened.get_task("OLD")["waiting_on"] == "仓库"
    reopened.close()


@pytest.mark.parametrize("deadline", ["bad", "2026-99-99T12:00:00Z", "2026-10-15T10:00:00", 123])
def test_bad_deadline_leaves_task_unchanged(deadline):
    store = CaseStore(); task = store.create_task("S", "核查")
    with pytest.raises(ValueError):
        store.update_task(task["task_id"], "in_progress", owner="测试", due_at=deadline)
    assert store.get_task(task["task_id"])["status"] == "pending"


def test_task_api_and_feedback_summary_do_not_fabricate_reviews():
    store = CaseStore(); app = app_with(cases=store); client = app.test_client()
    assert client.get("/api/feedback/summary").json["reviewed_n"] == 0
    created = client.post("/api/tasks", json={"session_id": "S1", "task_type": "核查"})
    task_id = created.json["task"]["task_id"]
    updated = client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress", "owner": "测试客服",
        "due_at": "2020-01-01T00:00:00Z", "waiting_on": "承运方"})
    assert updated.status_code == 200 and updated.json["task"]["overdue"]
    store.record_analysis(analysis_record())
    store.review("A1", "edited", "测试修订", "工程测试反馈", "测试人员")
    summary = client.get("/api/feedback/summary").json
    assert summary["reviewed_n"] == 1 and summary["decisions"]["edited"] == 1
    assert summary["automatic_learning"] is False
    assert client.get("/workbench").status_code == 200


def test_reopen_does_not_create_duplicate_active_risk():
    store = CaseStore()
    task = store.create_task("S1", "核查", risk_code="complaint")
    store.update_task(task["task_id"], "in_progress", owner="测试")
    store.update_task(task["task_id"], "resolved", "核查完成")
    store.create_task("S1", "核查", risk_code="complaint")
    with pytest.raises(ValueError, match="active task"):
        store.update_task(task["task_id"], "pending", "再次投诉")


def test_workflow_local_input_state_survives_process_store_restart(tmp_path):
    from src.orchestration.workbench_workflow import WorkbenchWorkflow
    from src.agents.assist_agent import AssistAgent
    from tests.test_service_guidance import Model, NoKnowledge
    from tests.test_workbench_v2 import data_store
    path = tmp_path / "state.sqlite"
    data = data_store(); sid = data.list_sessions()[0]["session_id"]
    cases = CaseStore(path)
    agent = AssistAgent(Model(draft()), NoKnowledge(), enable_evidence_routes=False)
    flow = WorkbenchWorkflow(data, agent, cases, lambda event: None)
    first = flow.run(sid, "我要退款", mode="snapshot")
    assert first["input_is_override"]
    cases.close()
    reopened = CaseStore(path)
    flow = WorkbenchWorkflow(data, agent, reopened, lambda event: None)
    prepared = flow.prepare(sid, "进度怎么样", None, "snapshot")
    assert any(row["message_text"] == "我要退款" for row in prepared["context"]["runtime_inputs"])
    replay = flow.prepare(sid, "进度怎么样", None, "replay")
    assert "runtime_inputs" not in replay["context"]


def test_retries_keep_cache_but_intervening_turn_changes_context():
    from src.orchestration.workbench_workflow import WorkbenchWorkflow
    from src.agents.assist_agent import AssistAgent
    from tests.test_service_guidance import Model, NoKnowledge
    from tests.test_workbench_v2 import data_store
    data = data_store(); sid = data.list_sessions()[0]["session_id"]
    model = Model(draft())
    flow = WorkbenchWorkflow(data, AssistAgent(model, NoKnowledge(), enable_evidence_routes=False),
                             CaseStore(), lambda event: None)
    first = flow.run(sid, "我要退款")
    for _ in range(3):
        repeated = flow.run(sid, "我要退款")
        assert repeated["cache_hit"]
        assert repeated["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert model.calls == 1
    flow.run(sid, "先别退款，帮我查物流")
    changed = flow.run(sid, "我要退款")
    assert not changed["cache_hit"] and model.calls == 3
    assert any(event["from"] == "deferred" and event["to"] == "active"
               for event in changed["service_state"]["transitions"])
    assert first["analysis_id"] != repeated["analysis_id"]
