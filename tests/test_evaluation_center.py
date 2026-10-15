import time

import pytest

from evaluation.evaluation_center import FrozenAnnotationAgent
from src.api.app_upgraded import create_app


def test_annotation_agent_reads_frozen_samples_and_rejects_unknown_evidence():
    store = FrozenAnnotationAgent(":memory:")
    sample = store.list_samples("heldout")[0]
    detail = store.get_sample(sample["sample_id"])
    assert detail["human_annotation"]["status"] == "pending"
    with pytest.raises(ValueError):
        store.save_annotation(sample["sample_id"], {
            "reviewer": "R1",
            "intent": "general_consultation",
            "emotion": "neutral",
            "risk_level": "低",
            "expected_facts": [],
            "supporting_evidence_ids": ["UNKNOWN"],
            "acceptable_next_action": "人工核实",
        })
    suggestion = store.suggest_annotation(sample["sample_id"])
    assert suggestion["status"] == "ai_suggestion_only"
    assert store.get_sample(sample["sample_id"])["human_annotation"]["status"] == "pending"


def test_annotation_agent_persists_label_and_reports_descriptive_coverage():
    store = FrozenAnnotationAgent(":memory:")
    sample = store.list_samples("heldout")[0]
    evidence = list(store.get_sample(sample["sample_id"])["context"]["evidence"])
    store.save_annotation(sample["sample_id"], {
        "reviewer": "R1",
        "intent": "general_consultation",
        "emotion": "neutral",
        "risk_level": "低",
        "expected_facts": ["当前消息需要人工判断"],
        "supporting_evidence_ids": [evidence[0]["id"]] if evidence else [],
        "acceptable_next_action": "人工核实",
    })
    report = store.annotation_report("heldout")
    assert report["progress"]["reviewed"] == 1
    assert report["metrics_status"].startswith("descriptive_human_labels_only")
    assert store.quality_report("heldout")["n"] == 1
    assert store.quality_report("heldout")["metrics_status"].startswith(
        "measured_against_human_labels"
    )


def test_efficiency_agent_requires_paired_trials_for_report():
    store = FrozenAnnotationAgent(":memory:")
    task = store.list_efficiency_tasks()[0]
    manual = store.start_trial(task["task_id"], "manual", "R1")
    time.sleep(0.001)
    store.stop_trial(manual["trial_id"], {
        "missed_facts": 2, "edit_count": 1, "success": True,
    })
    report = store.efficiency_report()
    assert report["completed_trials"] == 1
    assert report["paired_tasks"] == 0
    copilot = store.start_trial(task["task_id"], "copilot", "R1")
    store.stop_trial(copilot["trial_id"], {
        "missed_facts": 0, "edit_count": 0, "success": True,
    })
    report = store.efficiency_report()
    assert report["paired_tasks"] == 1
    assert "median_time_improvement_pct" in report


def test_evaluation_routes_are_available_and_isolated():
    app = create_app(evaluation_store=FrozenAnnotationAgent(":memory:"))
    client = app.test_client()
    assert client.get("/evaluation").status_code == 200
    listing = client.get("/api/evaluation/annotations?split=heldout")
    assert listing.status_code == 200
    assert listing.json["progress"]["total"] == 30
    tasks = client.get("/api/evaluation/efficiency/tasks")
    assert tasks.status_code == 200
    assert len(tasks.json["tasks"]) == 10


def test_export_report_writes_independent_artifacts(tmp_path):
    store = FrozenAnnotationAgent(":memory:")
    paths = store.export_report(tmp_path)
    assert paths["annotation"].is_file()
    assert paths["efficiency"].is_file()


def test_suggestion_route_does_not_write_human_label():
    app = create_app(evaluation_store=FrozenAnnotationAgent(":memory:"))
    client = app.test_client()
    sample_id = client.get("/api/evaluation/annotations?split=heldout").json["samples"][0]["sample_id"]
    response = client.get(f"/api/evaluation/annotations/{sample_id}/suggestion")
    assert response.status_code == 200
    assert response.json["status"] == "ai_suggestion_only"
    assert client.get(f"/api/evaluation/annotations/{sample_id}").json[
        "human_annotation"
    ]["status"] == "pending"
