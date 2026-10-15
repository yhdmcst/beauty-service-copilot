"""Experimental classifiers must keep splits separate and never act as human gold."""

import pytest

from evaluation.evaluate_lightweight_classifier import validate_protocol
from src.models.lightweight_classifier import LightweightTextClassifier


def test_experiment_rejects_frozen_or_unverified_protocols():
    with pytest.raises(ValueError, match="engineering"):
        validate_protocol({"human_labels": True})


def test_exact_split_overlap_is_rejected():
    with pytest.raises(ValueError, match="overlap"):
        validate_protocol({
            "origin": "engineering_behavior_specification", "human_labels": False,
            "development": [{"text": "退款"}], "validation": [{"text": "退款"}],
        })


def test_classifier_rejects_untrained_use_and_invalid_labels():
    classifier = LightweightTextClassifier(["neutral", "angry"])
    with pytest.raises(RuntimeError, match="Fit"):
        classifier.predict(["你好"])
    with pytest.raises(ValueError, match="Unknown"):
        classifier.fit([{"text": "你好", "basic": "neutral"}, {"text": "生气", "basic": "not-a-label"}], "basic")


def test_single_training_class_is_not_reported_as_learned_discrimination():
    with pytest.raises(ValueError, match="distinct"):
        LightweightTextClassifier(["neutral"]).fit([
            {"text": "你好", "basic": "neutral"}, {"text": "在吗", "basic": "neutral"},
        ], "basic")


def test_real_cpu_classifier_keeps_risk_and_human_decisions_outside_predictions():
    pytest.importorskip("sklearn")
    classifier = LightweightTextClassifier(["angry", "neutral"]).fit([
        {"text": "太生气，服务敷衍", "basic": "angry"}, {"text": "气死，服务很差", "basic": "angry"},
        {"text": "请查物流", "basic": "neutral"}, {"text": "您好查订单", "basic": "neutral"},
    ], "basic")
    result = classifier.predict(["服务太差", "$$$"])[0]
    assert result["model_calls"] == result["generation_tokens"] == 0
    assert result["can_override_service_risk"] is result["human_annotation"] is False
    unknown = classifier.predict(["$$$"])[0]
    assert unknown["label"] is None and unknown["review_required"]
