"""Audit reports must preserve raw labels and retain unmeasured denominators."""

import copy
import json

from evaluation.audit_frozen_labels import audit


def fixture():
    sample = {
        "sample_id": "F1", "analysis_point": "M1", "buyer_message": "你好",
        "context": {"messages": [{"role": "买家", "text": "你好"}], "evidence": [],
                    "analysis_mode": "replay", "analysis_at": "2026-05-01 10:00:00"},
    }
    label = {
        "sample_id": "F1", "split": "heldout", "status": "reviewed", "reviewer": "fixture",
        "intent": "general_consultation", "emotion": "neutral", "risk_level": "低",
        "expected_facts": json.dumps(["客户问候"]),
        "supporting_evidence_ids": "[]", "acceptable_next_action": "询问诉求",
        "updated_at": "2026-10-08T00:00:00+00:00", "label_source": "human", "notes": "",
    }
    return {"heldout": [sample]}, [label]


def test_audit_keeps_labels_and_has_no_recall_without_positives():
    pack, labels = fixture()
    original = copy.deepcopy(labels)
    report = audit(pack, labels)
    assert labels == original
    assert report["complete"]
    assert report["all"]["intent"]["correct"] == 1
    assert report["all"]["high_risk"]["positive_n"] == 0
    assert report["all"]["high_risk"]["recall"] is None


def test_audit_separates_assisted_labels():
    pack, labels = fixture()
    labels[0]["label_source"] = "assisted_human"
    report = audit(pack, labels)
    assert report["human_only"]["n"] == 0
    assert report["assisted_human"]["n"] == 1


def test_audit_does_not_count_invalid_references():
    pack, labels = fixture()
    labels[0]["supporting_evidence_ids"] = '["UNKNOWN"]'
    report = audit(pack, labels)
    assert not report["complete"]
    assert report["all"]["n"] == 0
    assert report["invalid_rows"][0]["reason"] == ["unknown_evidence"]
