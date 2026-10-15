"""Read-only heldout-label audit; preserve labels and do not tune predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.evaluation_center import (
    DEFAULT_DB, PACK_PATH, EMOTIONS, INTENTS, RISKS,
    FrozenAnnotationAgent, _normalize_context,
)
from src.agents.assist_agent import AssistAgent
from evaluation.annotation_provenance import provenance_report

LEVELS = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}


def audit(pack: dict, annotations: list[dict]) -> dict:
    """Compare strict labels, validate references, and retain every disagreement."""
    samples = {item["sample_id"]: item for item in pack["heldout"]}
    selected = [row for row in annotations
                if row["split"] == "heldout" and row["status"] == "reviewed"]
    provenance = provenance_report(selected)
    declared_human_ids = set(provenance["declared_human_sample_ids"])
    seen, invalid, predictions = set(), [], []
    agent = AssistAgent()
    for row in sorted(selected, key=lambda item: item["sample_id"]):
        sample_id = row["sample_id"]
        if sample_id not in samples:
            invalid.append({"sample_id": sample_id, "reason": "not_in_frozen_pack"})
            continue
        if sample_id in seen:
            invalid.append({"sample_id": sample_id, "reason": "duplicate_label"})
            continue
        seen.add(sample_id)
        sample = samples[sample_id]
        reasons = []
        if row["intent"] not in INTENTS or row["emotion"] not in EMOTIONS or row["risk_level"] not in RISKS:
            reasons.append("invalid_enum")
        if not str(row.get("reviewer", "")).strip() or not str(row.get("acceptable_next_action", "")).strip():
            reasons.append("required_field_missing")
        try:
            evidence = json.loads(row["supporting_evidence_ids"])
            facts = json.loads(row["expected_facts"])
            if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
                reasons.append("invalid_evidence_array")
                evidence = []
            if not isinstance(facts, list):
                reasons.append("invalid_fact_array")
                facts = []
        except (ValueError, TypeError):
            reasons.append("invalid_json")
            evidence, facts = [], []
        allowed_ids = {item["id"] for item in sample["context"]["evidence"]}
        if set(evidence) - allowed_ids:
            reasons.append("unknown_evidence")
        if reasons:
            invalid.append({"sample_id": sample_id, "reason": reasons})
            continue
        signals = agent.inspect(_normalize_context(sample), sample["buyer_message"], sample_id, "frozen-audit")
        predicted = {
            "intent": signals["intent"],
            "emotion": signals["special_emotion"] or signals["emotion_basic"],
            "risk_level": LEVELS[signals["risk_level_rule"]],
        }
        gold = {key: row[key] for key in predicted}
        predictions.append({
            "sample_id": sample_id, "analysis_point": sample["analysis_point"],
            "message": sample["buyer_message"], "label_source": row.get("label_source", "legacy_unspecified"),
            "effective_label_source": "human" if sample_id in declared_human_ids else row.get("label_source", "legacy_unspecified"),
            "reviewer": row["reviewer"], "updated_at": row["updated_at"],
            "gold": gold, "predicted": predicted,
            "basic_emotion": signals["emotion_basic"], "special_emotion": signals["special_emotion"],
            "matches": {key: gold[key] == predicted[key] for key in predicted},
            "supporting_evidence_ids": evidence, "expected_facts": facts,
            "acceptable_next_action": row["acceptable_next_action"],
            "notes": row.get("notes", ""),
        })

    def metrics(rows: list[dict]) -> dict:
        n = len(rows)
        result = {"n": n}
        for key in ("intent", "emotion", "risk_level"):
            pairs = [(row["gold"][key], row["predicted"][key]) for row in rows]
            result[key] = {
                "correct": sum(row["matches"][key] for row in rows), "n": n,
                "accuracy": sum(row["matches"][key] for row in rows) / n if n else None,
                "macro_f1": FrozenAnnotationAgent._macro_f1(pairs),
                "confusion": [
                    {"gold": gold, "predicted": pred, "n": count}
                    for (gold, pred), count in sorted(Counter(pairs).items())
                ],
            }
        positives = [row for row in rows if row["gold"]["risk_level"] in {"高", "紧急"}]
        negatives = [row for row in rows if row["gold"]["risk_level"] not in {"高", "紧急"}]
        tp = sum(row["predicted"]["risk_level"] in {"高", "紧急"} for row in positives)
        fp = sum(row["predicted"]["risk_level"] in {"高", "紧急"} for row in negatives)
        result["high_risk"] = {
            "positive_n": len(positives), "true_positive": tp,
            "recall": tp / len(positives) if positives else None,
            "negative_n": len(negatives), "false_positive": fp,
            "false_positive_rate": fp / len(negatives) if negatives else None,
        }
        return result

    sources = Counter(row["label_source"] for row in predictions)
    return {
        "scope": "current deterministic rules vs saved labels; not LLM reply/summary/citation quality",
        "strict_emotion_contract": "special_emotion if present else basic_emotion; mixed annotation vocabulary; provisional",
        "frozen_total": len(samples), "saved_reviewed_n": len(selected),
        "valid_label_n": len(predictions), "complete": len(predictions) == len(samples) and not invalid,
        "missing_ids": sorted(set(samples) - seen), "invalid_rows": invalid,
        "label_sources": provenance["effective_label_sources"],
        "recorded_label_sources": dict(sources),
        "annotation_provenance": provenance,
        "gold_risk_distribution": dict(Counter(row["gold"]["risk_level"] for row in predictions)),
        "all": metrics(predictions),
        "source_grouping_scope": "human_only/assisted_human use clarified origin; raw metadata subgroups retained separately",
        "human_only": metrics([row for row in predictions if row["effective_label_source"] == "human"]),
        "assisted_human": metrics([row for row in predictions if row["effective_label_source"] == "assisted_human"]),
        "raw_metadata_subgroups": {
            "human": metrics([row for row in predictions if row["label_source"] == "human"]),
            "assisted_human": metrics([row for row in predictions if row["label_source"] == "assisted_human"]),
        },
        "labels_and_predictions": predictions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--pack", type=Path, default=PACK_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/results/frozen_annotation_audit.json")
    args = parser.parse_args()
    pack_bytes = args.pack.read_bytes()
    pack = json.loads(pack_bytes)
    source = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    timestamp = datetime.now(timezone(timedelta(hours=8)))
    backup_dir = args.db.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"evaluation-frozen-{timestamp.strftime('%Y%m%d-%H%M%S-%f')}.sqlite"
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    saved = sqlite3.connect(backup)
    saved.row_factory = sqlite3.Row
    try:
        annotations = [dict(row) for row in saved.execute("SELECT * FROM annotations")]
        histories = saved.execute("SELECT COUNT(*) FROM annotation_history").fetchone()[0]
    finally:
        saved.close()
    report = audit(pack, annotations)
    report.update({
        "generated_at": timestamp.isoformat(),
        "pack_sha256": hashlib.sha256(pack_bytes).hexdigest(),
        "snapshot_path": str(backup),
        "snapshot_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "label_sha256": hashlib.sha256(
            json.dumps(sorted(annotations, key=lambda r: r["sample_id"]),
                       ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "annotation_history_count": histories,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "complete", "valid_label_n", "label_sources", "gold_risk_distribution", "all",
        "human_only", "assisted_human", "snapshot_path",
    )}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
