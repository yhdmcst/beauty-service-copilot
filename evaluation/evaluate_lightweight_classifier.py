"""Train only on engineering development wording; report all validation disagreements."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.emotion_agent import EmotionAgent
from src.agents.intent_agent import BeautyIntent, IntentAgent
from src.models.lightweight_classifier import LightweightTextClassifier


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_protocol(protocol: dict) -> None:
    if protocol.get("origin") != "engineering_behavior_specification" or protocol.get("human_labels") is not False:
        raise ValueError("This experiment accepts the explicit engineering protocol only, not frozen human gold.")
    development, validation = protocol["development"], protocol["validation"]
    if not development or not validation:
        raise ValueError("Require separate nonempty development and validation splits.")
    train_texts = {row["text"].strip() for row in development}
    if len(train_texts) != len(development) or any(
        row["text"].strip() in train_texts for row in validation
    ):
        raise ValueError("Exact duplicate training text or development/validation overlap.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evaluation/recognition_protocol_20261009.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Earlier experiments are retained.")
    original_hash = sha(args.protocol)
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    import sklearn

    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Optional scikit-learn shadow experiment on existing engineering wording, not independent accuracy",
        "human_gold": False, "human_review_completed": False, "live_workbench_changed": False,
        "frozen_human_data_used_for_training": False, "sklearn_version": sklearn.__version__,
        "protocol_sha256": original_hash,
        "training_split": "development", "training_n": len(protocol["development"]),
        "validation_n": len(protocol["validation"]), "seed": 42,
        "parameters": {"analyzer": "char", "ngram_range": [1, 4], "C": 4, "class_weight": "balanced"},
        "groups": {},
    }
    for field, labels in (
        ("intent", [item.value for item in BeautyIntent]),
        ("basic", ["angry", "fearful", "sad", "happy", "neutral"]),
    ):
        start = time.perf_counter()
        classifier = LightweightTextClassifier(labels).fit(protocol["development"], field)
        fit_ms = (time.perf_counter() - start) * 1000
        rows, latency = [], []
        for item in protocol["validation"]:
            start = time.perf_counter()
            result = classifier.predict([item["text"]])[0]
            latency.append((time.perf_counter() - start) * 1000)
            rule = IntentAgent().classify(item["text"])["intent_name"] if field == "intent" else \
                EmotionAgent().analyze(item["text"])["basic_emotion"]
            rows.append({
                "text": item["text"], "expected": item[field], "rule": rule,
                "classifier": result, "rule_match": rule == item[field],
                "classifier_match": result["label"] == item[field],
                "rule_classifier_disagree": rule != result["label"],
            })
        report["groups"][field] = {
            "n": len(rows), "rule_match_n": sum(row["rule_match"] for row in rows),
            "classifier_match_n": sum(row["classifier_match"] for row in rows),
            "disagreement_n": sum(row["rule_classifier_disagree"] for row in rows),
            "review_required_n": sum(row["classifier"]["review_required"] for row in rows),
            "training_label_counts": classifier.training_counts, "fit_ms": fit_ms,
            "median_predict_ms": statistics.median(latency),
            "adopted_as_workbench_classifier": False, "cases": rows,
        }
    assert sha(args.protocol) == original_hash
    report["protocol_unchanged"] = True
    report["implementation_sha256"] = {
        file: sha(ROOT / file) for file in (
            "src/models/lightweight_classifier.py", "evaluation/evaluate_lightweight_classifier.py",
            "src/agents/intent_agent.py", "src/agents/emotion_agent.py",
        )
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        field: {key: group[key] for key in (
            "n", "rule_match_n", "classifier_match_n", "review_required_n", "median_predict_ms",
        )} for field, group in report["groups"].items()
    }))


if __name__ == "__main__":
    main()
