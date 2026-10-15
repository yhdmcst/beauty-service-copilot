"""Automatic prechecks must not create human approval or ungrounded citations."""

import json

import pytest

from evaluation.review_saved_replies import (
    DIMENSIONS, export_promptfoo, input_cases, label_tasks, review_priority, review_route, validated_findings,
)


def findings(quote="退款"):
    return [{"dimension": dimension, "verdict": "issue", "reason": "待核对", "quote": quote}
            for dimension in DIMENSIONS]


def test_missing_or_duplicate_dimension_is_rejected():
    data = findings()
    data[0]["dimension"] = data[1]["dimension"]
    with pytest.raises(ValueError):
        validated_findings(json.dumps({"findings": data}), {"candidate": "退款"})


def test_invented_quote_cannot_be_reported_as_verified_issue():
    result = validated_findings(json.dumps({"findings": findings("根本不存在")}), {"candidate": "退款待核"})
    assert all(row["verdict"] == "uncertain" and not row["quote_verified"] for row in result)


def test_exact_quote_is_preserved_without_completing_human_review():
    result = validated_findings(json.dumps({"findings": findings()}), {"candidate": "退款待核"})
    assert all(row["verdict"] == "issue" and row["quote_verified"] for row in result)


def test_customer_complaint_alone_cannot_be_verified_as_candidate_issue():
    payload = {"buyer_message": "我的退款没到账", "candidate": {"suggested_reply": "客服核查流水后反馈"}}
    result = validated_findings(json.dumps({"findings": findings("我的退款没到账")}), payload)
    assert all(row["verdict"] == "uncertain" and not row["quote_verified"] for row in result)


def test_human_risk_and_rule_errors_cannot_be_dismissed_by_model_ok():
    row = {"result": {"risk_level": "紧急"}}
    score, reasons = review_priority(row, [{"code": "rule_failure"}], [], False)
    assert score >= 180 and len(reasons) == 2


def test_label_studio_predictions_and_blind_tasks_never_include_completed_annotations():
    row = {
        "case_id": "NEW", "buyer_message": "查退款", "evidence": [],
        "candidate": {"summary": "查退款", "suggested_reply": "待核查", "next_action": "核查"},
        "findings": [], "rule_issues": [],
    }
    blind = label_tasks([row], False)[0]
    assisted = label_tasks([row], True)[0]
    assert "predictions" not in blind and "annotations" not in blind
    assert "predictions" in assisted and "annotations" not in assisted
    assert assisted["predictions"][0]["result"][0]["value"]["choices"] == ["无法确认"]
    assert blind["meta"]["human_status"] == assisted["meta"]["human_status"] == "pending"


def test_invalid_or_unfinished_capture_cannot_be_reviewed():
    with pytest.raises(ValueError):
        input_cases({"capture_state": "running", "cases": []})


def test_promptfoo_echo_reuses_saved_output_and_explicit_local_judge():
    row = {
        "session_id": "NEW", "buyer_message": "查物流",
        "input_context": {"evidence": []},
        "result": {
            "summary": "买家查物流", "suggested_reply": "需核运单", "next_action": "核查轨迹",
            "evidence_ids": [],
        },
    }
    config = export_promptfoo([row], "qwen3:8b", "http://127.0.0.1:11436")
    assert config["providers"] == ["echo"]
    assert config["defaultTest"]["options"]["provider"]["id"] == "ollama:chat:qwen3:8b"
    assert config["tests"][0]["metadata"]["human_review_completed"] is False


def test_compact_checks_keep_five_dimensions_without_inventing_human_approval():
    raw = json.dumps({"checks": ["ok"] * 5, "findings": []})
    result = validated_findings(raw, {"candidate": "退款待核"}, compact=True)
    assert len(result) == 5
    assert all(item["verdict"] == "ok" and "待本人确认" in item["reason"] for item in result)


@pytest.mark.parametrize("raw", [
    {"checks": ["issue", "ok", "ok", "ok", "ok"], "findings": []},
    {"checks": ["ok"] * 5, "findings": findings()[:1]},
    {"checks": ["issue", "ok", "ok", "ok", "ok"],
     "findings": [{"dimension": "facts", "verdict": "uncertain", "reason": "待核", "quote": "退款"}]},
])
def test_compact_protocol_cannot_hide_missing_or_inconsistent_review(raw):
    with pytest.raises(ValueError):
        validated_findings(json.dumps(raw), {"candidate": "退款"}, compact=True)


@pytest.mark.parametrize("risk,rules,expected", [
    ("低", [], "compact"), ("高", [], "detailed"), ("紧急", [], "detailed"),
    ("低", [{"code": "known_order_requested_again"}], "rule_gate"),
    ("紧急", [{"code": "medical_claim"}], "rule_gate"),
])
def test_adaptive_review_never_uses_compact_checks_to_dismiss_risk_or_rules(risk, rules, expected):
    assert review_route({"result": {"risk_level": risk}}, rules, False, True) == expected
