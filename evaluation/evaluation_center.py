"""Human evaluation center for frozen annotations and paired efficiency trials."""

from __future__ import annotations

import json
import sqlite3
import statistics
import uuid
import threading
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents.emotion_agent import EmotionAgent
from src.agents.assist_agent import AssistAgent
from src.agents.intent_agent import IntentAgent
from src.risk.beauty_risk_rules import detect_risks
from evaluation.annotation_provenance import provenance_report

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "evaluation" / "holdout_v2" / "annotation_pack.json"
DEFAULT_DB = ROOT / "data" / "runtime" / "evaluation.sqlite"

INTENTS = {
    "ingredient_query", "skin_type_match", "usage_method", "authenticity_check",
    "effect_inquiry", "allergy_concern", "product_comparison", "order_query",
    "logistics_query", "refund_request", "quality_issue", "allergy_reaction",
    "coupon_query", "activity_inquiry", "invoice_request", "general_consultation",
    "unknown",
}
EMOTIONS = {
    "allergy_anxiety", "effect_disappointment", "price_dissatisfaction",
    "purchase_hesitation", "satisfaction", "neutral", "angry", "sad",
    "fearful", "happy", "待人工确认",
}
RISKS = {"低", "中", "高", "紧急"}
METHODS = {"manual", "copilot"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def synchronized(method):
    """Serialize the shared SQLite connection across local request threads."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


def _load_pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def _sample_lookup(pack: dict) -> dict[str, dict]:
    return {
        item["sample_id"]: {**item, "split": split}
        for split in ("development", "heldout")
        for item in pack.get(split, [])
    }


def _sample_evidence_ids(sample: dict) -> set[str]:
    return {
        str(item.get("id"))
        for item in sample.get("context", {}).get("evidence", [])
        if item.get("id")
    }


def _normalize_context(sample: dict) -> dict:
    """Adapt annotation-pack context to the safety agent's internal shape."""
    context = sample.get("context", {})
    messages = []
    for index, item in enumerate(context.get("messages", [])):
        role = "买家" if item.get("role") in {"买家", "buyer"} else item.get("role", "买家")
        messages.append({
            "message_id": item.get("message_id") or (
                sample.get("analysis_point", "") if index == len(context["messages"]) - 1
                else f"{sample['sample_id']}-{index}"),
            "发送时间": item.get("time", context.get("analysis_at", "")),
            "角色": role,
            "message_text": item.get("text", ""),
        })
    return {
        "messages": messages,
        "evidence": context.get("evidence", []),
        "analysis_point": sample.get("analysis_point", ""),
        "analysis_at": context.get("analysis_at", ""),
        "analysis_mode": context.get("analysis_mode", "replay"),
        "basis_warning": context.get("basis_warning", ""),
        "service_history": {
            "identity_basis": "unconfirmed",
            "contacts_7d": [],
            "refund_records_30d": [],
            "messages": [],
            "warning": "",
        },
    }


class FrozenAnnotationAgent:
    """Manage human labels without generating or silently filling them."""

    def __init__(self, db_path: str | Path = DEFAULT_DB, pack_path: str | Path = PACK_PATH) -> None:
        self.pack_path = Path(pack_path)
        self._pack = json.loads(self.pack_path.read_text(encoding="utf-8"))
        self.samples = _sample_lookup(self._pack)
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS annotations (
                sample_id TEXT PRIMARY KEY,
                split TEXT NOT NULL,
                status TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                intent TEXT NOT NULL,
                emotion TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                expected_facts TEXT NOT NULL,
                supporting_evidence_ids TEXT NOT NULL,
                acceptable_next_action TEXT NOT NULL,
                notes TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS efficiency_tasks (
                task_id TEXT PRIMARY KEY,
                sample_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                position INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS efficiency_trials (
                trial_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                method TEXT NOT NULL,
                operator TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                elapsed_ms INTEGER,
                missed_facts INTEGER,
                edit_count INTEGER,
                success INTEGER,
                outcome TEXT NOT NULL,
                notes TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS efficiency_exclusions (
                trial_id TEXT PRIMARY KEY,
                actor TEXT NOT NULL, reason TEXT NOT NULL, recorded_at TEXT NOT NULL
            );
            """
        )
        self.db.commit()
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(annotations)")}
        if "label_source" not in columns:
            self.db.execute("ALTER TABLE annotations ADD COLUMN label_source TEXT NOT NULL DEFAULT 'human'")
            self.db.commit()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS annotation_history "
            "(sample_id TEXT NOT NULL, reviewer TEXT NOT NULL, time TEXT NOT NULL, data TEXT NOT NULL)")
        self.db.commit()
        self._ensure_efficiency_tasks()

    @synchronized
    def close(self) -> None:
        self.db.close()

    @synchronized
    def list_samples(self, split: str = "heldout") -> list[dict]:
        if split not in {"development", "heldout", "all"}:
            raise ValueError("invalid split")
        ids = [
            sample_id for sample_id, sample in self.samples.items()
            if split == "all" or sample["split"] == split
        ]
        rows = {
            row["sample_id"]: dict(row)
            for row in self.db.execute("SELECT * FROM annotations")
        }
        result = []
        for sample_id in sorted(ids):
            sample = self.samples[sample_id]
            annotation = rows.get(sample_id)
            result.append({
                "sample_id": sample_id,
                "split": sample["split"],
                "family": sample.get("family_for_split_only", ""),
                "buyer_message": sample.get("buyer_message", ""),
                "analysis_at": sample.get("context", {}).get("analysis_at", ""),
                "status": annotation["status"] if annotation else "pending",
                "reviewer": annotation["reviewer"] if annotation else "",
            })
        return result

    @synchronized
    def get_sample(self, sample_id: str) -> dict:
        if sample_id not in self.samples:
            raise KeyError(sample_id)
        sample = self.samples[sample_id]
        row = self.db.execute(
            "SELECT * FROM annotations WHERE sample_id=?", (sample_id,),
        ).fetchone()
        annotation = dict(row) if row else {
            "status": "pending", "reviewer": "", "intent": "", "emotion": "",
            "risk_level": "", "expected_facts": "[]",
            "supporting_evidence_ids": "[]", "acceptable_next_action": "",
            "notes": "", "updated_at": "",
            "label_source": "human",
        }
        for key in ("expected_facts", "supporting_evidence_ids"):
            annotation[key] = json.loads(annotation[key])
        return {
            "sample_id": sample_id,
            "analysis_point": sample.get("analysis_point", ""),
            "split": sample["split"],
            "family": sample.get("family_for_split_only", ""),
            "buyer_message": sample.get("buyer_message", ""),
            "context": sample.get("context", {}),
            "human_annotation": annotation,
            "annotation_provenance": provenance_report([annotation]) if row else None,
        }

    def suggest_annotation(self, sample_id: str) -> dict:
        """Generate a review aid; never writes it as a human label."""
        if sample_id not in self.samples:
            raise KeyError(sample_id)
        sample = self.get_sample(sample_id)
        context = _normalize_context(sample)
        message = sample["buyer_message"]
        intent_agent = IntentAgent()
        emotion_agent = EmotionAgent()
        intent = intent_agent.classify(message)
        emotion = emotion_agent.analyze(message)
        risk_alerts = detect_risks(message)
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        risk = "low"
        if any(item["level"] == "critical" for item in risk_alerts):
            risk = "critical"
        elif any(item["level"] == "high" for item in risk_alerts):
            risk = "high"
        elif risk_alerts:
            risk = "medium"
        risk_label = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}[risk]
        evidence_ids = [str(item["id"]) for item in context["evidence"] if item.get("id")]
        return {
            "sample_id": sample_id,
            "status": "ai_suggestion_only",
            "warning": "此结果由规则辅助生成，不是人工金标准；保存前必须由人工核对。",
            "intent": intent["intent_name"],
            "emotion": emotion.get("special_emotion") or emotion.get("basic_emotion", "neutral"),
            "risk_level": risk_label,
            "expected_facts": [],
            "supporting_evidence_ids": evidence_ids[:5],
            "acceptable_next_action": (
                "高风险先人工接管并核实证据"
                if risk in {"high", "critical"} else
                "核对当前证据后形成客服回复"
            ),
            "risk_alerts": risk_alerts,
        }

    @synchronized
    def save_annotation(self, sample_id: str, payload: dict) -> dict:
        if sample_id not in self.samples:
            raise KeyError(sample_id)
        reviewer = payload.get("reviewer", "")
        if not isinstance(reviewer, str):
            raise ValueError("reviewer must be text")
        reviewer = reviewer.strip()
        intent = str(payload.get("intent", "")).strip()
        emotion = str(payload.get("emotion", "")).strip()
        risk_level = str(payload.get("risk_level", "")).strip()
        next_action = str(payload.get("acceptable_next_action", "")).strip()
        expected_facts = payload.get("expected_facts", [])
        evidence_ids = payload.get("supporting_evidence_ids", [])
        if not reviewer or not next_action:
            raise ValueError("reviewer and acceptable_next_action are required")
        if intent not in INTENTS:
            raise ValueError("invalid intent")
        if emotion not in EMOTIONS:
            raise ValueError("invalid emotion")
        if risk_level not in RISKS:
            raise ValueError("invalid risk_level")
        if not isinstance(expected_facts, list) or not all(isinstance(item, (str, dict)) for item in expected_facts):
            raise ValueError("expected_facts must be an array of strings or objects")
        if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
            raise ValueError("supporting_evidence_ids must be an array of strings")
        unknown = set(evidence_ids) - _sample_evidence_ids(self.samples[sample_id])
        if unknown:
            raise ValueError(f"unknown evidence ids: {sorted(unknown)}")
        notes = str(payload.get("notes", ""))[:1000]
        source = payload.get("label_source", "human")
        if source not in {"human", "assisted_human"}:
            raise ValueError("invalid label_source")
        split = self.samples[sample_id]["split"]
        values = (
            sample_id, split, "reviewed", reviewer[:80], intent, emotion, risk_level,
            _json(expected_facts), _json(evidence_ids), next_action[:500], notes, utc_now(), source,
        )
        self.db.execute(
            """
            INSERT INTO annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sample_id) DO UPDATE SET
                status=excluded.status, reviewer=excluded.reviewer, intent=excluded.intent,
                emotion=excluded.emotion, risk_level=excluded.risk_level,
                expected_facts=excluded.expected_facts,
                supporting_evidence_ids=excluded.supporting_evidence_ids,
                acceptable_next_action=excluded.acceptable_next_action,
                notes=excluded.notes, updated_at=excluded.updated_at,
                label_source=excluded.label_source
            """,
            values,
        )
        self.db.commit()
        annotation = self.get_sample(sample_id)["human_annotation"]
        self.db.execute("INSERT INTO annotation_history VALUES (?, ?, ?, ?)",
                        (sample_id, reviewer, utc_now(), _json(annotation)))
        self.db.commit()
        return annotation

    def annotation_progress(self, split: str = "heldout") -> dict:
        samples = self.list_samples(split)
        reviewed = sum(item["status"] == "reviewed" for item in samples)
        return {
            "split": split, "total": len(samples), "reviewed": reviewed,
            "pending": len(samples) - reviewed,
            "complete": bool(samples) and reviewed == len(samples),
        }

    @synchronized
    def annotation_report(self, split: str = "heldout") -> dict:
        """Return descriptive human-label coverage, never self-scored accuracy."""
        samples = self.list_samples(split)
        reviewed_ids = {
            item["sample_id"] for item in samples if item["status"] == "reviewed"
        }
        rows = [
            dict(row) for row in self.db.execute(
                "SELECT * FROM annotations WHERE sample_id IN ({})".format(
                    ",".join("?" for _ in reviewed_ids) or "''"
                ),
                tuple(reviewed_ids),
            )
        ] if reviewed_ids else []
        risk_counts: dict[str, int] = {}
        intent_counts: dict[str, int] = {}
        for row in rows:
            risk_counts[row["risk_level"]] = risk_counts.get(row["risk_level"], 0) + 1
            intent_counts[row["intent"]] = intent_counts.get(row["intent"], 0) + 1
        provenance = provenance_report(rows)
        return {
            "split": split,
            "progress": self.annotation_progress(split),
            "risk_distribution": risk_counts,
            "intent_distribution": intent_counts,
            "reviewed_with_evidence": sum(
                bool(json.loads(row["supporting_evidence_ids"])) for row in rows
            ),
            "assisted_annotation_n": provenance["effective_label_sources"].get("assisted_human", 0),
            "assisted_annotation_n_scope": "clarified origin; raw click-inferred markers retained in annotation_provenance",
            "annotation_provenance": provenance,
            "metrics_status": "descriptive_human_labels_only; model_accuracy_requires_gold_standard",
        }

    @staticmethod
    def _macro_f1(rows: list[tuple[str, str]]) -> float | None:
        labels = sorted({label for pair in rows for label in pair})
        if not rows or not labels:
            return None
        scores = []
        for label in labels:
            tp = sum(actual == label and predicted == label for actual, predicted in rows)
            fp = sum(actual != label and predicted == label for actual, predicted in rows)
            fn = sum(actual == label and predicted != label for actual, predicted in rows)
            precision = tp / (tp + fp) if tp + fp else 0
            recall = tp / (tp + fn) if tp + fn else 0
            scores.append(2 * precision * recall / (precision + recall)
                          if precision + recall else 0)
        return sum(scores) / len(scores)

    def quality_report(self, split: str = "heldout") -> dict:
        """Compare current deterministic safety/classification output to human labels."""
        reviewed_ids = {
            item["sample_id"] for item in self.list_samples(split)
            if item["status"] == "reviewed"
        }
        if not reviewed_ids:
            return {
                "split": split,
                "n": 0,
                "metrics_status": "not_measured; human_labels_pending",
            }
        agent = AssistAgent()
        intent_pairs, emotion_pairs, risk_pairs = [], [], []
        high_positive = high_true_positive = high_false_positive = 0
        for sample_id in sorted(reviewed_ids):
            sample = self.get_sample(sample_id)
            annotation = sample["human_annotation"]
            context = _normalize_context(sample)
            signals = agent.inspect(
                context, sample["buyer_message"], sample_id, f"quality-{sample_id}",
            )
            predicted_emotion = signals.get("special_emotion") or signals.get("emotion_basic")
            predicted_risk = {
                "low": "低", "medium": "中", "high": "高", "critical": "紧急",
            }[signals["risk_level_rule"]]
            intent_pairs.append((annotation["intent"], signals["intent"]))
            emotion_pairs.append((annotation["emotion"], predicted_emotion))
            risk_pairs.append((annotation["risk_level"], predicted_risk))
            gold_high = annotation["risk_level"] in {"高", "紧急"}
            predicted_high = predicted_risk in {"高", "紧急"}
            high_positive += gold_high
            high_true_positive += gold_high and predicted_high
            high_false_positive += (not gold_high) and predicted_high
        exact = lambda rows: sum(actual == predicted for actual, predicted in rows) / len(rows)
        provenance = provenance_report([
            self.get_sample(sid)["human_annotation"] for sid in reviewed_ids])
        return {
            "split": split,
            "n": len(reviewed_ids),
            "metrics_status": "measured_against_human_labels; small_sample",
            "prediction_scope": "deterministic rules only; NOT LLM summary/reply/citation accuracy",
            "complete_set": len(reviewed_ids) == len(self.list_samples(split)),
            "assisted_annotation_n": provenance["effective_label_sources"].get("assisted_human", 0),
            "assisted_annotation_n_scope": "clarified origin; raw click-inferred markers retained separately",
            "annotation_provenance": provenance,
            "intent_accuracy": exact(intent_pairs),
            "intent_macro_f1": self._macro_f1(intent_pairs),
            "emotion_accuracy": exact(emotion_pairs),
            "emotion_macro_f1": self._macro_f1(emotion_pairs),
            "risk_accuracy": exact(risk_pairs),
            "risk_macro_f1": self._macro_f1(risk_pairs),
            "high_risk_recall": high_true_positive / high_positive if high_positive else None,
            "high_risk_false_positive_rate": (
                high_false_positive / (len(reviewed_ids) - high_positive)
                if len(reviewed_ids) > high_positive else None
            ),
        }

    def _ensure_efficiency_tasks(self) -> None:
        existing = self.db.execute("SELECT COUNT(*) FROM efficiency_tasks").fetchone()[0]
        if existing:
            return
        candidates = [
            item for item in self.list_samples("heldout")
            if item["sample_id"] in self.samples
        ][:10]
        for position, item in enumerate(candidates, 1):
            self.db.execute(
                "INSERT INTO efficiency_tasks VALUES (?, ?, ?, ?, ?)",
                (
                    f"E{position:02d}-{item['sample_id']}", item["sample_id"],
                    f"{item['family'] or '客服场景'} · 服务轨迹处理",
                    "找出当前问题、相关证据、风险和下一步处置建议",
                    position,
                ),
            )
        self.db.commit()

    @synchronized
    def list_efficiency_tasks(self) -> list[dict]:
        tasks = []
        for row in self.db.execute("SELECT * FROM efficiency_tasks ORDER BY position"):
            task = dict(row)
            trials = [
                dict(item) for item in self.db.execute(
                    "SELECT * FROM efficiency_trials WHERE task_id=? ORDER BY started_at",
                    (task["task_id"],),
                )
            ]
            exclusions = {item["trial_id"]: dict(item) for item in self.db.execute(
                "SELECT * FROM efficiency_exclusions")}
            for trial in trials:
                trial["exclusion"] = exclusions.get(trial["trial_id"])
            task["trials"] = trials
            task["sample"] = self.get_sample(task["sample_id"])
            task["recommended_order"] = ["manual", "copilot"] if task["position"] % 2 else ["copilot", "manual"]
            tasks.append(task)
        return tasks

    @synchronized
    def start_trial(self, task_id: str, method: str, operator: str) -> dict:
        if method not in METHODS:
            raise ValueError("method must be manual or copilot")
        if not operator.strip():
            raise ValueError("operator is required")
        task = self.db.execute(
            "SELECT 1 FROM efficiency_tasks WHERE task_id=?", (task_id,),
        ).fetchone()
        if not task:
            raise KeyError(task_id)
        active = self.db.execute(
            "SELECT 1 FROM efficiency_trials WHERE task_id=? AND method=? AND ended_at IS NULL",
            (task_id, method),
        ).fetchone()
        if active:
            raise ValueError("an active trial already exists")
        if self.db.execute(
            """SELECT 1 FROM efficiency_trials t
            WHERE task_id=? AND method=? AND operator=? AND ended_at IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM efficiency_exclusions e WHERE e.trial_id=t.trial_id)""",
            (task_id, method, operator.strip()[:80]),
        ).fetchone():
            raise ValueError("this operator already completed this task/method")
        trial_id = str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO efficiency_trials VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, '', '')",
            (trial_id, task_id, method, operator.strip()[:80], utc_now()),
        )
        self.db.commit()
        return self.get_trial(trial_id)

    @synchronized
    def get_trial(self, trial_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM efficiency_trials WHERE trial_id=?", (trial_id,),
        ).fetchone()
        if not row:
            raise KeyError(trial_id)
        result = dict(row)
        exclusion = self.db.execute(
            "SELECT * FROM efficiency_exclusions WHERE trial_id=?", (trial_id,),
        ).fetchone()
        result["exclusion"] = dict(exclusion) if exclusion else None
        return result

    @synchronized
    def invalidate_trial(self, trial_id: str, actor: str, reason: str) -> dict:
        """Retain original elapsed time while excluding an interrupted/practice run."""
        if not actor.strip() or not reason.strip():
            raise ValueError("操作者和作废原因必填")
        trial = self.get_trial(trial_id)
        if trial["exclusion"]:
            raise ValueError("本次计时已作废")
        with self.db:
            if not trial["ended_at"]:
                ended = utc_now()
                elapsed_ms = max(0, int((datetime.fromisoformat(ended) -
                    datetime.fromisoformat(trial["started_at"])).total_seconds() * 1000))
                self.db.execute(
                    "UPDATE efficiency_trials SET ended_at=?,elapsed_ms=? WHERE trial_id=?",
                    (ended, elapsed_ms, trial_id))
            self.db.execute("INSERT INTO efficiency_exclusions VALUES (?, ?, ?, ?)",
                            (trial_id, actor.strip()[:80], reason.strip()[:1000], utc_now()))
        return self.get_trial(trial_id)

    @synchronized
    def stop_trial(self, trial_id: str, payload: dict) -> dict:
        trial = self.get_trial(trial_id)
        if trial["ended_at"]:
            raise ValueError("trial already stopped")
        missed = payload.get("missed_facts", 0)
        edits = payload.get("edit_count", 0)
        success = payload.get("success", False)
        if isinstance(missed, bool) or not isinstance(missed, int) or missed < 0:
            raise ValueError("missed_facts must be a non-negative integer")
        if isinstance(edits, bool) or not isinstance(edits, int) or edits < 0:
            raise ValueError("edit_count must be a non-negative integer")
        if not isinstance(success, bool):
            raise ValueError("success must be boolean")
        ended = utc_now()
        started = datetime.fromisoformat(trial["started_at"])
        elapsed_ms = max(0, int((datetime.fromisoformat(ended) - started).total_seconds() * 1000))
        self.db.execute(
            """
            UPDATE efficiency_trials
            SET ended_at=?, elapsed_ms=?, missed_facts=?, edit_count=?, success=?,
                outcome=?, notes=?
            WHERE trial_id=?
            """,
            (
                ended, elapsed_ms, missed, edits, int(success),
                str(payload.get("outcome", ""))[:500],
                str(payload.get("notes", ""))[:1000], trial_id,
            ),
        )
        self.db.commit()
        return self.get_trial(trial_id)

    def trial_context(self, trial_id: str) -> dict:
        trial = self.get_trial(trial_id)
        task = self.db.execute(
            "SELECT * FROM efficiency_tasks WHERE task_id=?", (trial["task_id"],),
        ).fetchone()
        sample = self.get_sample(task["sample_id"])
        return {
            "trial": trial, "title": task["objective"],
            "sample": {key: sample[key] for key in ("sample_id", "analysis_point", "buyer_message", "context")},
        }

    @synchronized
    def efficiency_report(self) -> dict:
        rows = [
            dict(row) for row in self.db.execute(
                """SELECT * FROM efficiency_trials t WHERE ended_at IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM efficiency_exclusions e WHERE e.trial_id=t.trial_id)""",
            )
        ]
        by_method = {}
        for method in sorted(METHODS):
            values = [row["elapsed_ms"] for row in rows if row["method"] == method]
            by_method[method] = {
                "n": len(values),
                "median_ms": statistics.median(values) if values else None,
                "success_rate": (
                    sum(row["success"] for row in rows if row["method"] == method) / len(values)
                    if values else None
                ),
                "median_missed_facts": (
                    statistics.median(row["missed_facts"] for row in rows if row["method"] == method)
                    if values else None
                ),
                "median_edit_count": (
                    statistics.median(row["edit_count"] for row in rows if row["method"] == method)
                    if values else None
                ),
            }
        pairs = {}
        for task in self.db.execute("SELECT task_id FROM efficiency_tasks"):
            task_id = task["task_id"]
            operators = {row["operator"] for row in rows if row["task_id"] == task_id}
            for operator in sorted(operators):
                pair = {row["method"]: row for row in rows
                        if row["task_id"] == task_id and row["operator"] == operator}
                if not METHODS <= pair.keys():
                    continue
                pairs[f"{task_id}:{operator}"] = {
                    "manual_ms": pair["manual"]["elapsed_ms"],
                    "copilot_ms": pair["copilot"]["elapsed_ms"],
                    "time_saved_ms": pair["manual"]["elapsed_ms"] - pair["copilot"]["elapsed_ms"],
                    "missed_facts_delta": pair["manual"]["missed_facts"] - pair["copilot"]["missed_facts"],
                    "edit_count_delta": pair["manual"]["edit_count"] - pair["copilot"]["edit_count"],
                }
        paired = list(pairs.values())
        return {
            "completed_trials": len(rows),
            "excluded_trial_n": self.db.execute(
                "SELECT COUNT(*) FROM efficiency_exclusions").fetchone()[0],
            "paired_tasks": len(paired),
            "by_method": by_method,
            "paired": pairs,
            "scope": "paired within task and operator; self-reported omissions; practice/order bias remains",
            "median_time_saved_ms": statistics.median(
                item["time_saved_ms"] for item in paired
            ) if paired else None,
            "median_time_improvement_pct": (
                statistics.median(
                    item["time_saved_ms"] / item["manual_ms"] * 100
                    for item in paired if item["manual_ms"] > 0
                ) if any(item["manual_ms"] > 0 for item in paired) else None
            ),
        }

    def export_report(self, output_dir: str | Path | None = None) -> dict[str, Path]:
        """Export current annotation coverage and paired-study results."""
        target = Path(output_dir or (ROOT / "evaluation" / "results"))
        target.mkdir(parents=True, exist_ok=True)
        annotation = {
            "generated_at": utc_now(),
            "heldout": self.annotation_report("heldout"),
            "development": self.annotation_report("development"),
            "quality": {
                "heldout": self.quality_report("heldout"),
                "development": self.quality_report("development"),
            },
            "labels": [self.get_sample(item["sample_id"]) for item in self.list_samples("all")
                       if item["status"] == "reviewed"],
        }
        efficiency = {"generated_at": utc_now(), **self.efficiency_report()}
        annotation_path = target / "human_annotation_report.json"
        efficiency_path = target / "efficiency_study_report.json"
        annotation_path.write_text(
            json.dumps(annotation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        efficiency_path.write_text(
            json.dumps(efficiency, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"annotation": annotation_path, "efficiency": efficiency_path}

    def export_suggestions(self, split: str = "heldout",
                           output_dir: str | Path | None = None) -> Path:
        """Export candidate labels separately from human annotations."""
        target = Path(output_dir or (ROOT / "evaluation" / "results"))
        target.mkdir(parents=True, exist_ok=True)
        suggestions = [
            self.suggest_annotation(item["sample_id"])
            for item in self.list_samples(split)
        ]
        path = target / f"{split}_ai_annotation_suggestions.json"
        path.write_text(
            json.dumps({
                "generated_at": utc_now(),
                "split": split,
                "status": "ai_suggestion_only",
            "warning": "Not a gold standard and not included in model metrics.",
                "samples": suggestions,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


class EfficiencyStudyAgent:
    """Thin orchestration facade for the paired human efficiency study."""

    def __init__(self, store: FrozenAnnotationAgent) -> None:
        self.store = store

    def task_instructions(self, task_id: str, method: str) -> dict:
        tasks = {item["task_id"]: item for item in self.store.list_efficiency_tasks()}
        if task_id not in tasks or method not in METHODS:
            raise KeyError(task_id)
        task = tasks[task_id]
        return {
            "task_id": task_id,
            "method": method,
            "title": task["title"],
            "objective": task["objective"],
            "sample_id": task["sample_id"],
            "instructions": (
                "仅使用当前样本提供的合法上下文完成任务；"
                + ("不要点击生成辅助建议。" if method == "manual" else "可以使用客服副驾生成并审核建议。")
            ),
        }
