"""Alternate review formats on the same saved candidates; never mark human approval."""

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

from evaluation.review_saved_replies import (
    CompactVerdict, Verdict, input_cases, judge_prompt,
    review_payload, review_route, rule_review, validated_findings,
)
from src.models.qwen_wrapper import QwenWrapper, is_loopback_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--base", default="http://127.0.0.1:11435")
    parser.add_argument("--rounds", type=int, default=2, choices=(1, 2))
    args = parser.parse_args()
    if args.output.exists() or not is_loopback_url(args.base):
        raise ValueError("New output and explicit loopback model are required.")
    raw = args.input.read_bytes()
    cases = input_cases(json.loads(raw))
    import httpx
    from openai import OpenAI

    client = OpenAI(api_key="ollama-local", base_url=args.base.rstrip("/") + "/v1", max_retries=0,
                    http_client=httpx.Client(trust_env=False, timeout=90))
    model = QwenWrapper(model_name=args.model, client=client, provider="ollama")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Alternating local grader formats, fixed saved candidates; not customer/human accuracy",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "model": args.model, "rounds": args.rounds, "human_review_completed": False,
        "same_model_self_judge": args.model == json.loads(raw).get("model"),
        "sampling": "All first attempts retained including errors, rule gates and format disagreements",
        "measurements": [], "capture_state": "running",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        for round_index in range(args.rounds):
            for position, case in enumerate(cases):
                payload, rules = review_payload(case), rule_review(case)
                order = ("detailed", "adaptive") if (round_index + position) % 2 == 0 else ("adaptive", "detailed")
                for phase in order:
                    route = review_route(case, rules, False, phase == "adaptive")
                    stamp = time.perf_counter()
                    row = {
                        "round": round_index + 1, "case_id": case.get("session_id") or case["sample_id"],
                        "phase": phase, "route": route, "input_tokens": 0, "output_tokens": 0,
                        "model_called": route != "rule_gate", "findings": [], "raw": "", "error": None,
                        "rule_issues": rules,
                    }
                    if route != "rule_gate":
                        try:
                            result = model.generate_structured(
                                judge_prompt(payload, route == "compact"),
                                CompactVerdict.model_json_schema() if route == "compact" else Verdict.model_json_schema(),
                                max_tokens=480,
                            )
                            row.update(raw=result.text, input_tokens=result.input_tokens,
                                       output_tokens=result.output_tokens)
                            row["findings"] = validated_findings(result.text, payload, route == "compact")
                        except Exception as error:
                            row["error"] = type(error).__name__
                    row["wall_ms"] = (time.perf_counter() - stamp) * 1000
                    row["flagged"] = bool(rules) or bool(row["error"]) or any(
                        finding["verdict"] != "ok" for finding in row["findings"])
                    report["measurements"].append(row)
                    save()
                print(f"round={round_index + 1} {row['case_id']} completed", flush=True)
        report["capture_state"] = "complete"
    finally:
        model.close()
        report["ended_at"] = datetime.now(timezone.utc).isoformat()
        groups = {}
        for phase in ("detailed", "adaptive"):
            rows = [row for row in report["measurements"] if row["phase"] == phase]
            groups[phase] = {
                "n": len(rows), "model_calls": sum(row["model_called"] for row in rows),
                "error_n": sum(bool(row["error"]) for row in rows),
                "flagged_n": sum(row["flagged"] for row in rows),
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
                "median_ms": statistics.median(row["wall_ms"] for row in rows) if rows else None,
            }
        report["summary"] = groups
        report["disagreements"] = [{
            "case_id": a["case_id"], "round": a["round"], "first": a["phase"],
            "detailed_or_adaptive_flagged": [a["flagged"], b["flagged"]],
        } for a, b in zip(report["measurements"][::2], report["measurements"][1::2])
            if a["flagged"] != b["flagged"]]
        save()
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
