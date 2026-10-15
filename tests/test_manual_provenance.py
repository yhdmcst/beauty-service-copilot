"""Manual-origin attestation never rewrites answers or proves blind independence."""

import copy
import json

import pytest

from evaluation.annotation_provenance import provenance_report
from evaluation.evaluation_center import FrozenAnnotationAgent
from src.api.app_upgraded import create_app
from src.ops.case_store import CaseStore
from src.agents.assist_agent import AssistAgent
from tests.test_workbench_v2 import Model


def test_user_clarification_preserves_raw_source_and_is_revision_bound(tmp_path):
    row = {"sample_id": "F1", "updated_at": "T1", "label_source": "assisted_human"}
    original = copy.deepcopy(row)
    path = tmp_path / "origin.json"
    path.write_text(json.dumps({
        "declared_origin": "human_judgment", "statement": "clicked accidentally, judged manually",
        "label_versions": {"F1": "T1"},
    }), encoding="utf-8")
    result = provenance_report([row], path)
    assert row == original
    assert result["raw_label_sources"] == {"assisted_human": 1}
    assert result["effective_label_sources"] == {"human": 1}
    assert result["declared_human_n"] == 1
    assert result["independent_blind_annotation_status"] == "not_verified"
    result = provenance_report([{**row, "updated_at": "T2"}], path)
    assert result["declared_human_n"] == 0


def test_candidate_request_does_not_change_saved_manual_origin():
    store = FrozenAnnotationAgent(":memory:")
    sample = store.list_samples("heldout")[0]["sample_id"]
    data = {
        "reviewer": "fixture", "intent": "general_consultation", "emotion": "neutral",
        "risk_level": "低", "expected_facts": [], "supporting_evidence_ids": [],
        "acceptable_next_action": "核实", "label_source": "human",
    }
    store.save_annotation(sample, data)
    store.suggest_annotation(sample)
    assert store.get_sample(sample)["human_annotation"]["label_source"] == "human"
    store.close()


def test_invalidate_active_trial_keeps_record_and_allows_new_valid_pair(tmp_path):
    path = tmp_path / "study.sqlite"
    store = FrozenAnnotationAgent(path)
    task = store.list_efficiency_tasks()[0]["task_id"]
    old = store.start_trial(task, "manual", "fixture")
    excluded = store.invalidate_trial(old["trial_id"], "fixture", "误开计时并中断")
    assert excluded["ended_at"] and excluded["elapsed_ms"] >= 0
    assert excluded["exclusion"]["reason"] == "误开计时并中断"
    assert store.efficiency_report()["completed_trials"] == 0
    assert store.efficiency_report()["excluded_trial_n"] == 1
    for method in ("manual", "copilot"):
        trial = store.start_trial(task, method, "fixture")
        store.stop_trial(trial["trial_id"], {"missed_facts": 0, "edit_count": 0, "success": True})
    assert store.efficiency_report()["completed_trials"] == 2
    assert store.efficiency_report()["paired_tasks"] == 1
    store.close()
    reopened = FrozenAnnotationAgent(path)
    assert reopened.get_trial(old["trial_id"])["exclusion"]
    assert reopened.efficiency_report()["paired_tasks"] == 1
    reopened.close()


def test_invalidate_completed_trial_removes_pair_without_deleting_result():
    store = FrozenAnnotationAgent(":memory:")
    task = store.list_efficiency_tasks()[0]["task_id"]
    ids = []
    for method in ("manual", "copilot"):
        trial = store.start_trial(task, method, "fixture")
        store.stop_trial(trial["trial_id"], {"missed_facts": 2, "edit_count": 1, "success": True})
        ids.append(trial["trial_id"])
    assert store.efficiency_report()["paired_tasks"] == 1
    store.invalidate_trial(ids[0], "fixture", "确认是练习，不纳入正式测量")
    assert store.efficiency_report()["paired_tasks"] == 0
    assert store.get_trial(ids[0])["missed_facts"] == 2
    with pytest.raises(ValueError):
        store.invalidate_trial(ids[0], "fixture", "不能重复作废")
    store.close()


def test_invalidation_api_requires_reason_and_keeps_frozen_annotations():
    app = create_app(case_store=CaseStore(), assist_agent=AssistAgent(Model()),
                     evaluation_store=FrozenAnnotationAgent(":memory:"))
    client = app.test_client()
    task = client.get("/api/evaluation/efficiency/tasks").json["tasks"][0]["task_id"]
    trial = client.post("/api/evaluation/efficiency/trials",
                        json={"task_id": task, "method": "manual", "operator": "fixture"}).json["trial"]
    route = f"/api/evaluation/efficiency/trials/{trial['trial_id']}/invalidate"
    assert client.post(route, json={"operator": "fixture", "reason": ""}).status_code == 400
    assert client.post(route, json={"operator": "fixture", "reason": "练习"}).status_code == 200
    data = client.get("/api/evaluation/efficiency/tasks").json
    assert data["report"]["paired_tasks"] == 0 and data["report"]["excluded_trial_n"] == 1
    assert client.get("/api/evaluation/annotations").json["progress"]["reviewed"] == 0
    assert client.get("/health").json["evaluation_revision"] == "manual-evaluation-v2"
    app.extensions["analysis_jobs"].close()
