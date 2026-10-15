"""Measure final basic emotion on saved engineering expressions, never human gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.capture_precheck_cases import RecordedQwen
from src.agents.assist_agent import AssistAgent


class NoKnowledge:
    def search(self, message: str, intent: str) -> dict:
        return {"reason": "no_approved_knowledge", "confidence": 0, "can_auto_reply": False,
                "retrieved_docs": [], "verified_context": ""}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Retain prior measurements.")
    protocol_path = ROOT / "evaluation/emotion_protocol_20261013.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    load_dotenv(ROOT / ".env")
    model = RecordedQwen()
    if model.provider != "ollama":
        model.close()
        raise ValueError("Configured loopback Ollama only.")
    agent = AssistAgent(model, NoKnowledge(), enable_evidence_routes=False)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "full draft on existing engineering emotion expressions; not human/independent accuracy",
        "prompt_version": agent.prompt_version, "human_gold": False,
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "capture_state": "running", "groups": {}, "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for group in ("development", "validation"):
            for position, item in enumerate(protocol[group], 1):
                context = {
                    "analysis_point": f"{group}-{position}", "analysis_at": "2026-10-13 12:00:00",
                    "analysis_mode": "replay", "messages": [], "evidence": [],
                }
                start = len(model.calls)
                result = agent.assist(context, item["text"], f"{group}-{position}")
                report["cases"].append({
                    **item, "group": group, "result": result,
                    "model_calls": model.calls[start:],
                    "basic_match": result.get("emotion_basic_display") == item["basic"],
                    "fallback": result["model_status"] == "fallback",
                })
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"{group} {position} basic_match={report['cases'][-1]['basic_match']}", flush=True)
        report["capture_state"] = "complete"
    finally:
        model.close()
        report["ended_at"] = datetime.now(timezone.utc).isoformat()
        report["groups"] = {
            group: {"n": len(rows), "basic_match_n": sum(row["basic_match"] for row in rows),
                    "fallback_n": sum(row["fallback"] for row in rows)}
            for group in ("development", "validation")
            for rows in [[row for row in report["cases"] if row["group"] == group]]
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["groups"]))


if __name__ == "__main__":
    main()
