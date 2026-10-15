"""First-pass, non-blind engineering regression of the original 30 heldout cases.

The evaluator participated in development. This is post-development regression,
not independent accuracy, human review, or human efficiency measurement.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sqlite3
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

BASIC_EMOTIONS = {"neutral", "fearful", "angry", "sad", "happy"}
GOLD_SCENE_TO_BASIC = {
    "allergy_anxiety": "fearful",
    "price_dissatisfaction": "angry",
    "effect_disappointment": "sad",
    "satisfaction": "happy",
}
RISK_NAMES = {
    "low": "\u4f4e", "medium": "\u4e2d", "high": "\u9ad8", "critical": "\u7d27\u6025",
}
HIGH_RISKS = {RISK_NAMES["high"], RISK_NAMES["critical"]}
DISCLOSURE = {
    "activity": "post_development_engineering_regression",
    "measurement_actor": "ai",
    "evaluator_participated_in_development": True,
    "independent_blind_test": False,
    "human_review_completed": False,
    "human_efficiency_measured": False,
    "sampling": "Every frozen heldout sample once, in unique sample_id order; no best-of selection.",
    "scope": "Current AssistAgent including production routing, validation and safety floors.",
    "timing_scope": "Sequential system wall time only; not human task completion time.",
    "gold_policy": "Original saved labels unchanged; explicit emotion mapping disclosed separately.",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    """Replace only this run's snapshots, keeping readable progress between writes."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def error_record(error: BaseException) -> dict:
    return {
        "error_type": type(error).__name__, "message": str(error),
        "traceback": traceback.format_exc(),
    }


def read_annotations(db_path: Path) -> list[dict]:
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        return [dict(row) for row in connection.execute("SELECT * FROM annotations")]
    finally:
        connection.close()


def validate_labels(
    samples: list[dict], annotations: list[dict],
    intents: set[str], emotions: set[str], risks: set[str],
) -> dict:
    """Apply the frozen audit contract without repairing any saved label."""
    lookup = {sample["sample_id"]: sample for sample in samples}
    reviewed = [
        row for row in annotations if row.get("split") == "heldout"
        and row.get("status") == "reviewed"
    ]
    counts = Counter(row["sample_id"] for row in reviewed)
    valid, invalid = {}, []
    for row in sorted(reviewed, key=lambda item: item["sample_id"]):
        sample_id = row["sample_id"]
        reasons = []
        if sample_id not in lookup:
            reasons.append("not_in_frozen_pack")
        if counts[sample_id] != 1:
            reasons.append("duplicate_label")
        if (row.get("intent") not in intents or row.get("emotion") not in emotions
                or row.get("risk_level") not in risks):
            reasons.append("invalid_enum")
        if (not str(row.get("reviewer") or "").strip()
                or not str(row.get("acceptable_next_action") or "").strip()):
            reasons.append("required_field_missing")
        try:
            evidence = json.loads(row["supporting_evidence_ids"])
            facts = json.loads(row["expected_facts"])
            if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
                reasons.append("invalid_evidence_array")
                evidence = []
            if not isinstance(facts, list):
                reasons.append("invalid_fact_array")
        except (ValueError, TypeError, KeyError):
            reasons.append("invalid_json")
            evidence = []
        if sample_id in lookup:
            allowed = {item["id"] for item in lookup[sample_id]["context"]["evidence"]}
            if set(evidence) - allowed:
                reasons.append("unknown_evidence")
        if reasons:
            invalid.append({"sample_id": sample_id, "reasons": reasons, "original_label": row})
        else:
            valid[sample_id] = row
    return {
        "valid": valid, "reviewed": reviewed, "invalid_rows": invalid,
        "frozen_n": len(samples), "reviewed_heldout_n": len(reviewed),
        "valid_label_n": len(valid),
        "unscorable_sample_ids": sorted(set(lookup) - set(valid)),
        "missing_reviewed_sample_ids": sorted(set(lookup) - set(counts)),
    }


def field_metrics(rows: list[dict]) -> dict:
    """Missing outputs remain errors in the denominator, without a fake F1 class."""
    n = len(rows)
    correct = sum(row["predicted"] == row["gold"] for row in rows)
    labels = sorted(
        {row["gold"] for row in rows}
        | {row["predicted"] for row in rows if row["predicted"] is not None}
    )
    per_label = []
    for label in labels:
        tp = sum(row["gold"] == label and row["predicted"] == label for row in rows)
        fp = sum(row["gold"] != label and row["predicted"] == label for row in rows)
        fn = sum(row["gold"] == label and row["predicted"] != label for row in rows)
        denominator = 2 * tp + fp + fn
        per_label.append({
            "label": label, "support": sum(row["gold"] == label for row in rows),
            "tp": tp, "fp": fp, "fn": fn,
            "f1": 2 * tp / denominator if denominator else 0.0,
        })
    confusion = Counter((row["gold"], row["predicted"]) for row in rows)
    return {
        "n": n, "correct": correct, "accuracy": correct / n if n else None,
        "macro_f1": sum(item["f1"] for item in per_label) / len(per_label) if per_label else None,
        "macro_f1_contract": "Unweighted gold/present-prediction label union; missing outputs count as FN.",
        "missing_prediction_n": sum(row["predicted"] is None for row in rows),
        "per_label": per_label,
        "confusion": [
            {"gold": gold, "predicted": prediction, "n": count}
            for (gold, prediction), count in sorted(
                confusion.items(), key=lambda item: (item[0][0], item[0][1] or ""))
        ],
        "disagreements": [row for row in rows if row["gold"] != row["predicted"]],
    }


def risk_metrics(rows: list[dict]) -> dict:
    positives = [row for row in rows if row["gold"] in HIGH_RISKS]
    negatives = [row for row in rows if row["gold"] not in HIGH_RISKS]
    tp = sum(row["predicted"] in HIGH_RISKS for row in positives)
    fp = sum(row["predicted"] in HIGH_RISKS for row in negatives)
    return {
        "positive_n": len(positives), "true_positive": tp,
        "recall": tp / len(positives) if positives else None,
        "negative_n": len(negatives), "false_positive": fp,
        "false_positive_rate": fp / len(negatives) if negatives else None,
        "missing_prediction_n": sum(row["predicted"] is None for row in rows),
        "positive_levels": sorted(HIGH_RISKS),
        "interpretation": "Zero high-risk gold positives means recall is unmeasured, not zero or one.",
    }


def measurements(cases: list[dict], labels: dict[str, dict]) -> dict:
    comparisons, mapped, excluded, mapping_rows, rule_final = [], [], [], [], []
    for sample_id, gold in sorted(labels.items()):
        original = gold["emotion"]
        target = original if original in BASIC_EMOTIONS else GOLD_SCENE_TO_BASIC.get(original)
        if target is None:
            excluded.append({
                "sample_id": sample_id, "original_gold": original,
                "reason": ("purchase_hesitation_has_no_unique_basic_mapping"
                           if original == "purchase_hesitation" else "no_explicit_basic_mapping"),
            })
        else:
            mapping_rows.append({
                "sample_id": sample_id, "original_gold": original, "mapped_basic_gold": target,
                "mapping_kind": "identity" if original in BASIC_EMOTIONS else "explicit_scene_mapping",
            })
    mappings = {row["sample_id"]: row for row in mapping_rows}
    for case in cases:
        sample_id = case["sample_id"]
        if sample_id not in labels:
            continue
        gold = labels[sample_id]
        signals, result = case.get("signals") or {}, case.get("result") or {}
        rule = {
            "intent": signals.get("intent"),
            "emotion": signals.get("special_emotion") or signals.get("emotion_basic"),
            "risk_level": RISK_NAMES.get(signals.get("risk_level_rule")),
        }
        final = {
            "intent": result.get("intent"), "risk_level": result.get("risk_level"),
            # emotion_basic remains a rule signal even on successful model output.
            "emotion_basic": result.get("emotion_basic_display"),
        }
        comparisons.append({
            "sample_id": sample_id, "original_gold": {
                key: gold[key] for key in ("intent", "emotion", "risk_level")},
            "rule_predictions": rule, "final_predictions": final,
            "model_status": result.get("model_status"), "failure": case["failure"],
        })
        if sample_id in mappings:
            mapped.append({
                **mappings[sample_id], "gold": mappings[sample_id]["mapped_basic_gold"],
                "predicted": final["emotion_basic"],
                "prediction_field": "result.emotion_basic_display",
                "display_emotion": result.get("emotion"), "raw_model_emotion": result.get("emotion_model"),
                "emotion_source": result.get("emotion_source"),
                "rule_basic_emotion": signals.get("emotion_basic"),
                "model_status": result.get("model_status"),
            })
        if (rule["intent"] != final["intent"] or rule["risk_level"] != final["risk_level"]
                or signals.get("emotion_basic") != final["emotion_basic"]):
            rule_final.append({
                "sample_id": sample_id, "original_gold": comparisons[-1]["original_gold"],
                "rule": rule, "rule_basic_emotion": signals.get("emotion_basic"),
                "final": final, "emotion_source": result.get("emotion_source"),
                "intent_source": result.get("intent_source"),
            })

    def rows_for(kind: str, field: str) -> list[dict]:
        return [{
            "sample_id": row["sample_id"], "gold": row["original_gold"][field],
            "predicted": row[kind][field],
        } for row in comparisons]

    rule_metrics = {
        field: field_metrics(rows_for("rule_predictions", field))
        for field in ("intent", "emotion", "risk_level")
    }
    rule_metrics["high_risk"] = risk_metrics(rows_for("rule_predictions", "risk_level"))
    final_metrics = {
        field: field_metrics(rows_for("final_predictions", field))
        for field in ("intent", "risk_level")
    }
    final_metrics["high_risk"] = risk_metrics(rows_for("final_predictions", "risk_level"))
    return {
        **DISCLOSURE,
        "processed_n": len(cases), "valid_label_n": len(labels),
        "scored_processed_n": len(comparisons),
        "pending_valid_sample_ids": sorted(set(labels) - {row["sample_id"] for row in comparisons}),
        "failure_policy": "All attempted valid-label cases retained; missing fields are incorrect, not excluded.",
        "rule_original_mixed_labels_strict": {
            "scope": "Original mixed vocabulary, exactly as audit_frozen_labels; no emotion mapping.",
            "emotion_contract": "signals.special_emotion if present else signals.emotion_basic",
            "n": len(comparisons), "metrics": rule_metrics,
        },
        "final_basic_emotion_explicit_mapping": {
            "scope": "Engineering match rate against explicitly mapped original gold, not independent accuracy.",
            "prediction_field": "result.emotion_basic_display",
            "forbidden_substitute": "result.emotion or signals/result.emotion_basic",
            "basic_identity_labels": sorted(BASIC_EMOTIONS),
            "original_gold_to_basic_mapping": GOLD_SCENE_TO_BASIC,
            "eligible_label_n": len(mapping_rows), "excluded_n": len(excluded), "excluded": excluded,
            "mapping_rows": mapping_rows, "metrics": field_metrics(mapped), "cases": mapped,
        },
        "final_intent_and_risk_original_labels_strict": {
            "scope": "Final adopted intent/risk including unchanged production safety floors.",
            "n": len(comparisons), "metrics": final_metrics,
        },
        "label_comparisons": comparisons, "rule_final_disagreements": rule_final,
        "gold_risk_distribution": dict(Counter(row["risk_level"] for row in labels.values())),
        "model_status_counts": dict(Counter(
            (case.get("result") or {}).get("model_status", "agent_exception") for case in cases)),
        "cases_with_model_calls": sum(bool(case["model_calls"]) for case in cases),
        "successful_provider_calls": sum(
            "raw_text" in call for case in cases for call in case["model_calls"]),
        "failed_provider_calls": sum(
            "error_type" in call for case in cases for call in case["model_calls"]),
        "failure_n": sum(case["failure"] is not None for case in cases),
        "missing_final_basic_n": sum(
            (case.get("result") or {}).get("emotion_basic_display") is None for case in cases),
    }


def implementation_hashes() -> dict[str, str]:
    paths = list((ROOT / "src").rglob("*.py")) + [
        Path(__file__), ROOT / "evaluation" / "evaluation_center.py",
        ROOT / "evaluation" / "audit_frozen_labels.py",
        ROOT / "evaluation" / "capture_precheck_cases.py",
        ROOT / "evaluation" / "annotation_provenance.py",
    ]
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in sorted(paths)}


def evaluate(output: Path, db_path: Path, pack_path: Path) -> dict:
    # Runtime imports happen after argparse so --help cannot initialize inference.
    from dotenv import load_dotenv
    from evaluation.capture_precheck_cases import RecordedQwen, digest, read_protected_records
    from evaluation.evaluation_center import EMOTIONS, INTENTS, RISKS, _normalize_context
    from evaluation.annotation_provenance import ORIGIN_PATH, provenance_report
    from src.agents.assist_agent import AssistAgent
    from src.models.qwen_wrapper import configured_model, is_loopback_url

    output, db_path, pack_path = output.resolve(), db_path.resolve(), pack_path.resolve()
    if output.exists():
        raise FileExistsError("Retain previous evidence; --output must be a new directory.")
    load_dotenv(ROOT / ".env", override=True)
    endpoint = os.getenv("QWEN_API_BASE", "")
    if os.getenv("QWEN_PROVIDER") != "ollama" or not is_loopback_url(endpoint):
        raise ValueError("Project .env must explicitly configure loopback Ollama.")
    if urlsplit(endpoint).port != 11435:
        raise ValueError("This GPU regression is pinned to the authorized Ollama port 11435.")
    if int(os.getenv("QWEN_MAX_ATTEMPTS", "1")) != 1:
        raise ValueError("First-pass capture requires QWEN_MAX_ATTEMPTS=1; do not retry/select outputs.")
    if (os.getenv("CACHE_BACKEND", "memory") != "memory"
            or os.getenv("VECTOR_BACKEND", "memory") != "memory"
            or os.getenv("EMBEDDING_BACKEND", "local") != "local"):
        raise ValueError("This read-only regression requires process-local cache/retrieval backends.")
    pack_bytes = pack_path.read_bytes()
    pack = json.loads(pack_bytes)
    samples = pack["heldout"]
    ids = [sample["sample_id"] for sample in samples]
    if len(ids) != 30 or len(set(ids)) != 30:
        raise ValueError("Require all original 30 unique heldout sample_ids; no subset or deduplication.")
    samples = sorted(samples, key=lambda sample: sample["sample_id"])
    before, _ = read_protected_records(db_path)
    annotations = read_annotations(db_path)
    annotation_order = sorted(
        annotations, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))
    if before["annotations"] != {"n": len(annotations), "sha256": digest(annotation_order)}:
        raise RuntimeError("Annotations changed between read-only source transactions.")
    label_audit = validate_labels(samples, annotations, INTENTS, EMOTIONS, RISKS)
    labels = label_audit.pop("valid")
    reviewed = label_audit.pop("reviewed")
    provenance = provenance_report(reviewed)
    source_paths = {
        "project_env": ROOT / ".env", "annotation_origin_clarification": ORIGIN_PATH,
    }
    source_hashes = {name: file_hash(path) for name, path in source_paths.items() if path.is_file()}
    manifest = {
        **DISCLOSURE, "started_at": utc_now(), "state": "running",
        "db_path": str(db_path), "sqlite_mode": "ro",
        "pack_path": str(pack_path), "output_directory": str(output),
        "sample_order": [sample["sample_id"] for sample in samples],
        "before": before, "annotation_pack_sha256_before": hashlib.sha256(pack_bytes).hexdigest(),
        "source_file_sha256_before": source_hashes,
        "implementation_sha256_before": implementation_hashes(),
        "annotation_provenance": provenance, "label_validation": label_audit,
        "after": None, "annotation_pack_sha256_after": None,
        "original_human_records_unchanged": None, "annotation_pack_unchanged": None,
        "implementation_unchanged": None,
    }
    output.mkdir(parents=True, exist_ok=False)
    # Persist source fingerprints before constructing a model or making any call.
    write_json(output / "source_manifest.json", manifest)
    case_dir = output / "cases"
    case_dir.mkdir()
    write_json(output / "original_reviewed_labels.json", {
        "scope": "Unmodified reviewed heldout annotations, not AI reviews.",
        "labels": reviewed, "provenance": provenance, "validation": label_audit,
    })
    report = {
        **DISCLOSURE, "started_at": manifest["started_at"], "capture_state": "running",
        "total_n": 30, "processed_n": 0, "provider": "ollama", "endpoint": endpoint,
        "model": configured_model(), "prompt_version": AssistAgent.prompt_version,
        "transport_max_attempts": 1, "warmup_calls": [], "cases": [],
    }
    model = None
    failure = None
    started = time.perf_counter()

    def save_progress(active_sample_id: str | None = None) -> None:
        report["processed_n"] = len(report["cases"])
        write_json(output / "assistance_cases.json", report)
        write_json(output / "progress.json", {
            "updated_at": utc_now(), "capture_state": report["capture_state"],
            "processed_n": report["processed_n"], "total_n": 30,
            "active_sample_id": active_sample_id,
            "last_completed_sample_id": report["cases"][-1]["sample_id"] if report["cases"] else None,
            "failure_n": sum(case["failure"] is not None for case in report["cases"]),
        })
        write_json(output / "metrics.json", {
            "generated_at": utc_now(), "capture_state": report["capture_state"],
            "source_integrity_verified": (
                manifest["original_human_records_unchanged"] is True
                and manifest["annotation_pack_unchanged"] is True
                and manifest["implementation_unchanged"] is True
                and manifest.get("source_files_unchanged") is True),
            **measurements(report["cases"], labels),
        })

    try:
        save_progress()
        model = RecordedQwen()
        if model.provider != "ollama" or not is_loopback_url(str(model.client.base_url)):
            raise ValueError("RecordedQwen must use the pinned loopback Ollama endpoint.")
        agent = AssistAgent(model)
        for position, sample in enumerate(samples, 1):
            sample_id = sample["sample_id"]
            context = _normalize_context(sample)
            analysis_id = f"frozen-assistance-{sample_id}"
            case = {
                "position": position, "sample_id": sample_id, "started_at": utc_now(),
                "capture_state": "running", "frozen_sample": sample,
                "input_context": context, "input_context_sha256": digest(context),
                "buyer_message": sample["buyer_message"], "analysis_point": sample["analysis_point"],
                "assist_arguments": {"session_id": sample_id, "analysis_id": analysis_id},
                "signals": None, "result": None, "model_calls": [], "raw": [],
                "failure": None, "wall_ms": None,
            }
            path = case_dir / f"{position:02d}_{sample_id}.json"
            write_json(path, case)
            save_progress(sample_id)
            print(json.dumps({
                "event": "case_started", "position": position, "total": 30, "sample_id": sample_id,
            }), flush=True)
            call_start = len(model.calls)
            case_started = time.perf_counter()
            try:
                signals = agent.inspect(context, sample["buyer_message"], sample_id, analysis_id)
                case["signals"] = copy.deepcopy(signals)
                case["inspect_ms"] = round((time.perf_counter() - case_started) * 1000, 2)
                write_json(path, case)
                assist_started = time.perf_counter()
                case["result"] = agent.assist(
                    context, sample["buyer_message"], session_id=sample_id,
                    analysis_id=analysis_id, signals=signals,
                )
                case["assist_ms"] = round((time.perf_counter() - assist_started) * 1000, 2)
                result = case["result"]
                case["emotion_resolution"] = {
                    "final_basic_field": "result.emotion_basic_display",
                    "final_basic": result.get("emotion_basic_display"),
                    "display_emotion": result.get("emotion"),
                    "raw_model_emotion": result.get("emotion_model"),
                    "emotion_source": result.get("emotion_source"),
                    "rule_basic": case["signals"].get("emotion_basic"),
                    "rule_scene": case["signals"].get("special_emotion"),
                    "missing_final_basic_is_not_replaced_by_rule": True,
                }
                if result.get("model_status") == "fallback":
                    case["failure"] = {
                        "kind": "assist_fallback", "error_type": result.get("error"),
                        "validation_flags": result.get("validation_flags", []),
                    }
                if result.get("cache_hit"):
                    case["failure"] = {"kind": "unexpected_cache_hit", "not_first_pass_generation": True}
                case["capture_state"] = "complete"
            except Exception as error:
                case["failure"] = {"kind": "agent_exception", **error_record(error)}
                case["capture_state"] = "failed"
            except BaseException as error:
                case["failure"] = {"kind": "interrupted", **error_record(error)}
                case["capture_state"] = "interrupted"
                raise
            finally:
                case["ended_at"] = utc_now()
                case["wall_ms"] = round((time.perf_counter() - case_started) * 1000, 2)
                case["model_calls"] = copy.deepcopy(model.calls[call_start:])
                case["raw"] = [
                    {"call_index": index, "raw_text": call.get("raw_text"),
                     "error_type": call.get("error_type")}
                    for index, call in enumerate(case["model_calls"], 1)
                ]
                write_json(path, case)
                report["cases"].append(case)
                save_progress()
                print(json.dumps({
                    "event": "case_finished", "position": position, "total": 30,
                    "sample_id": sample_id, "capture_state": case["capture_state"],
                    "model_status": (case["result"] or {}).get("model_status"),
                    "model_calls": len(case["model_calls"]), "wall_ms": case["wall_ms"],
                    "failure": case["failure"],
                }, ensure_ascii=True), flush=True)
        report["capture_state"] = "complete"
    except BaseException as error:
        failure = error
        report["capture_state"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        report["failure"] = error_record(error)
    finally:
        report["ended_at"] = utc_now()
        report["system_wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
        manifest["ended_at"] = report["ended_at"]
        manifest["state"] = report["capture_state"]
        integrity_errors = []
        try:
            after, _ = read_protected_records(db_path)
            manifest["after"] = after
            manifest["original_human_records_unchanged"] = before == after
        except Exception as error:
            integrity_errors.append({"source": "protected_records", **error_record(error)})
        try:
            manifest["annotation_pack_sha256_after"] = file_hash(pack_path)
            manifest["annotation_pack_unchanged"] = (
                manifest["annotation_pack_sha256_before"] == manifest["annotation_pack_sha256_after"])
            manifest["implementation_sha256_after"] = implementation_hashes()
            manifest["implementation_unchanged"] = (
                manifest["implementation_sha256_before"] == manifest["implementation_sha256_after"])
            manifest["source_file_sha256_after"] = {
                name: file_hash(path) for name, path in source_paths.items() if path.is_file()
            }
            manifest["source_files_unchanged"] = (
                source_hashes == manifest["source_file_sha256_after"])
        except Exception as error:
            integrity_errors.append({"source": "frozen_files", **error_record(error)})
        manifest["integrity_check_errors"] = integrity_errors
        if model is not None:
            try:
                model.close()
            except Exception as error:
                report["model_close_error"] = error_record(error)
        write_json(output / "source_manifest.json", manifest)
        save_progress()
    if failure is not None:
        raise failure
    if (integrity_errors or manifest["original_human_records_unchanged"] is not True
            or manifest["annotation_pack_unchanged"] is not True
            or manifest["implementation_unchanged"] is not True
            or manifest["source_files_unchanged"] is not True):
        raise RuntimeError("Source integrity failed; retain all outputs and investigate.")
    return measurements(report["cases"], labels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New evidence directory; existing directories are rejected.")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "runtime" / "evaluation.sqlite",
                        help="Original annotation database, opened only with SQLite mode=ro.")
    parser.add_argument("--pack", type=Path, default=ROOT / "evaluation" / "holdout_v2" / "annotation_pack.json",
                        help="Frozen annotation pack; require all 30 unique heldout inputs.")
    args = parser.parse_args()
    result = evaluate(args.output, args.db, args.pack)
    print(json.dumps({
        "event": "regression_finished", "output": str(args.output.resolve()),
        "processed_n": result["processed_n"], "valid_label_n": result["valid_label_n"],
        "failure_n": result["failure_n"],
        "rule_original_mixed_labels_strict": result["rule_original_mixed_labels_strict"]["metrics"],
        "final_basic_emotion_explicit_mapping": result["final_basic_emotion_explicit_mapping"]["metrics"],
        "final_intent_and_risk_original_labels_strict":
            result["final_intent_and_risk_original_labels_strict"]["metrics"],
    }, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
