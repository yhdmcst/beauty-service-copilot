"""Capture first-pass local replies for AI precheck, without human-record writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from src.agents.assist_agent import AssistAgent
from src.data.contest_data import ContestDataStore
from src.models.qwen_wrapper import Generation, QwenWrapper
from src.ops.case_store import CaseStore
from src.orchestration.workbench_workflow import WorkbenchWorkflow

REPLY_CASES = (
    "S00381", "S00107", "S00029", "S00154", "S00082", "S00001",
    "S00004", "S00007", "S00008", "S00009", "S00012", "S00014",
)
PROTECTED_TABLES = (
    "annotations", "annotation_history", "efficiency_tasks",
    "efficiency_trials", "efficiency_exclusions",
)
METADATA = {"actor_code": "227", "actor_type": "ai",
            "status": "pending_human_confirmation"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_protected_records(db_path: Path) -> tuple[dict, list[dict]]:
    """Use a read-only transaction to fingerprint original human evidence."""
    db = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        manifest = {}
        for table in PROTECTED_TABLES:
            rows = [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]
            rows.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))
            manifest[table] = {"n": len(rows), "sha256": digest(rows)}
        tasks = [dict(row) for row in db.execute(
            "SELECT * FROM efficiency_tasks ORDER BY position")]
        return manifest, tasks
    finally:
        db.close()


def selected_context(data: ContestDataStore, session_id: str) -> dict:
    """Pin the first buyer problem; do not accidentally evaluate a final thanks."""
    session = data.get_session(session_id)
    if not session["message_choices"]:
        raise ValueError(f"No buyer analysis point: {session_id}")
    return data.get_session(
        session_id, before_message_id=session["message_choices"][0]["id"],
        analysis_mode="replay")


class RecordedQwen(QwenWrapper):
    """Preserve raw provider text as well as the validated final UI draft."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    def generate_with_usage(
        self, prompt: str, max_tokens: int = 300,
        response_schema: dict | None = None,
    ) -> Generation:
        call = {"started_at": utc_now(), "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "max_tokens": max_tokens, "response_schema": response_schema}
        started = time.perf_counter()
        try:
            result = super().generate_with_usage(prompt, max_tokens, response_schema)
            call.update(raw_text=result.text, model=result.model,
                        input_tokens=result.input_tokens, output_tokens=result.output_tokens)
            return result
        except Exception as error:
            call["error_type"] = type(error).__name__
            raise
        finally:
            call["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            call["ended_at"] = utc_now()
            self.calls.append(call)


def capture(output: Path, kind: str = "precheck") -> dict:
    """Run the production graph with an explicitly isolated in-memory case store."""
    output.mkdir(parents=True, exist_ok=True)
    protected_outputs = ("reply_cases.json", "source_manifest.json", "efficiency_inputs.json")
    if any((output / name).exists() for name in protected_outputs):
        raise FileExistsError("Existing evidence retained; choose a new output directory.")
    if kind not in {"precheck", "regression"}:
        raise ValueError("kind must be precheck or regression")
    metadata = METADATA if kind == "precheck" else {
        "actor_type": "ai", "activity": "software_regression",
        "status": "not_human_quality_review",
    }
    load_dotenv(ROOT / ".env")
    model = RecordedQwen()
    if model.provider != "ollama":
        model.close()
        raise ValueError("Only explicitly configured loopback Ollama is permitted.")
    db_path = ROOT / "data" / "runtime" / "evaluation.sqlite"
    pack_path = ROOT / "evaluation" / "holdout_v2" / "annotation_pack.json"
    pack_hash = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    before, tasks = read_protected_records(db_path)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    samples = {row["sample_id"]: row for row in pack["heldout"]}
    if kind == "precheck":
        write_json(output / "efficiency_inputs.json", {
            **metadata, "generated_at": utc_now(),
            "scope": "Frozen task inputs only; no human trial or quality decision generated.",
            "tasks": [{**task, "sample": samples[task["sample_id"]],
                       "recommended_order": ["manual", "copilot"] if task["position"] % 2
                       else ["copilot", "manual"]} for task in tasks],
        })
    manifest = {
        **metadata, "generated_at": utc_now(),
        "before": before, "annotation_pack_sha256_before": pack_hash,
    }
    write_json(output / "source_manifest.json", manifest)
    data = ContestDataStore(ROOT / "data" / "contest")
    cases = CaseStore(":memory:")
    agent = AssistAgent(model)
    flow = WorkbenchWorkflow(data, agent, cases, lambda event: None)
    report = {
        **metadata, "started_at": utc_now(), "capture_state": "running",
        "source_type": "contest_mock", "model": model.model, "provider": model.provider,
        "prompt_version": agent.prompt_version, "analysis_mode": "replay",
        "human_review_completed": False, "human_efficiency_measured": False,
        "selection": "12 predeclared scenarios, first buyer problem; not independent heldout accuracy",
        "sampling": "one first-pass reply per case, including fallbacks; no best-of selection",
        "case_store": ":memory:; not the user's live analyses, tasks or reviews",
        "measurement_scope": "sequential local system wall time; not human completion time",
        "implementation_sha256": {
            str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (
                Path("src/agents/assist_agent.py"), Path("src/knowledge/business_claims.py"),
                Path("src/knowledge/service_guidance.py"), Path("src/risk/beauty_risk_rules.py"),
                Path("src/agents/intent_agent.py"), Path("src/agents/emotion_agent.py"),
                Path("src/optimization/evidence_routing.py"),
                Path("src/optimization/smart_cache.py"),
                Path("src/data/contest_data.py"), Path("src/models/qwen_wrapper.py"),
                Path("src/utils/service_requests.py"),
                Path("src/utils/service_issue_cues.py"),
                Path("src/knowledge/communication_brief.py"),
                Path("src/knowledge/provided_information.py"),
                Path("src/agents/knowledge_agent.py"),
                Path("src/knowledge/answerable_gate.py"),
                Path("src/knowledge/rag_engine.py"),
            ) if (ROOT / path).exists()
        },
        "cases": [],
    }
    try:
        warmup_start = len(model.calls)
        try:
            model.generate_with_usage("Reply only: ready.", max_tokens=12)
        except Exception as error:
            report["warmup_error_type"] = type(error).__name__
        report["warmup_calls"] = model.calls[warmup_start:]
        for position, session_id in enumerate(REPLY_CASES, 1):
            context = selected_context(data, session_id)
            started, call_start = time.perf_counter(), len(model.calls)
            result = flow.run(session_id, point=context["analysis_point"], mode="replay")
            row = {
                "position": position, "session_id": session_id,
                "analysis_point": context["analysis_point"],
                "buyer_message": context["latest_buyer_message"],
                "input_context": context,
                "input_context_sha256": digest(context),
                "model_calls": model.calls[call_start:],
                "result": result,
                "wall_ms": round((time.perf_counter() - started) * 1000, 2),
                "human_decision": None,
            }
            report["cases"].append(row)
            write_json(output / "reply_cases.json", report)
            print(json.dumps({
                "position": position, "session_id": session_id,
                "model_status": result["model_status"], "wall_ms": row["wall_ms"],
                "flags": result.get("validation_flags", []),
            }, ensure_ascii=True), flush=True)
        report["capture_state"] = "complete"
    except Exception as error:
        report.update(capture_state="failed", error_type=type(error).__name__)
        raise
    finally:
        report["ended_at"] = utc_now()
        after, _ = read_protected_records(db_path)
        after_pack_hash = hashlib.sha256(pack_path.read_bytes()).hexdigest()
        manifest.update(
            after=after, annotation_pack_sha256_after=after_pack_hash,
            original_human_records_unchanged=before == after,
            annotation_pack_unchanged=pack_hash == after_pack_hash,
        )
        write_json(output / "source_manifest.json", manifest)
        write_json(output / "reply_cases.json", report)
        cases.close()
        model.close()
    if not manifest["original_human_records_unchanged"] or not manifest["annotation_pack_unchanged"]:
        raise RuntimeError("Original source changed during capture; investigate before approval.")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "evaluation" / "results" / "precheck_227")
    parser.add_argument("--kind", choices=("precheck", "regression"), default="precheck")
    args = parser.parse_args()
    capture(args.output, args.kind)


if __name__ == "__main__":
    main()
