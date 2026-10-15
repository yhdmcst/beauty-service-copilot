"""Reject invalid comparisons instead of manufacturing quality improvement."""

import copy

import pytest

from evaluation.capture_precheck_cases import digest
from evaluation.summarize_quality_regression import summarize


def report():
    context = {
        "analysis_at": "2026-06-08 11:00:00", "evidence": [],
        "messages": [],
    }
    return {
        "model": "same-model", "analysis_mode": "replay", "prompt_version": "test",
        "cases": [{
            "session_id": "NEW", "analysis_point": "BUYER-1",
            "buyer_message": "在吗", "input_context": context,
            "input_context_sha256": digest(context), "wall_ms": 100,
            "result": {
                "summary": "买家询问是否在线", "suggested_reply": "您好，请问需要咨询什么",
                "next_action": "确认买家具体问题", "intent": "general_consultation",
                "evidence_ids": [], "model_status": "fixture",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }],
    }


def test_identical_reports_do_not_claim_accuracy_or_efficiency():
    result = summarize(report(), report())
    assert result["input_token_change_pct"] == 0
    assert result["human_quality_rate"] is None
    assert result["human_efficiency_improvement"] is None
    assert result["after"]["n"] == 1


@pytest.mark.parametrize("field", ["analysis_point", "buyer_message", "input_context_sha256"])
def test_changed_input_cannot_be_used_as_same_case_comparison(field):
    old, new = report(), report()
    new["cases"][0][field] = "CHANGED"
    with pytest.raises(ValueError, match="differs"):
        summarize(old, new)


def test_duplicate_cases_are_rejected():
    old, new = report(), report()
    new["cases"].append(copy.deepcopy(new["cases"][0]))
    with pytest.raises(ValueError, match="unique"):
        summarize(old, new)
