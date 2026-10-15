"""Alternate saved before/after generation protocols on one local model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from src.agents.assist_agent import AssistanceDraft
from src.models.qwen_wrapper import QwenWrapper


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=2, choices=(1, 2, 3))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Existing benchmark evidence retained.")
    before, after = (json.loads(path.read_text(encoding="utf-8"))
                     for path in (args.before, args.after))
    if before["model"] != after["model"]:
        raise ValueError("Models must match.")
    pairs = []
    by_id = {row["session_id"]: row for row in before["cases"]}
    for row in after["cases"]:
        original = by_id[row["session_id"]]
        if original["input_context_sha256"] != row["input_context_sha256"]:
            raise ValueError("Input contexts differ.")
        if original["model_calls"] and row["model_calls"]:
            pairs.append((original, row))
    if not pairs:
        raise ValueError("No common model-generation cases.")
    load_dotenv(ROOT / ".env")
    model = QwenWrapper()
    if model.provider != "ollama":
        model.close()
        raise ValueError("Loopback Ollama only.")
    report = {
        "started_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "two prompt/schema versions; alternate same-case local provider requests; not production/human efficiency or independent quality",
        "model": model.model, "rounds": args.rounds, "common_case_n": len(pairs),
        "excluded_rule_only_cases": len(after["cases"]) - len(pairs),
        "temperature": 0, "max_tokens": 360, "provider_attempts": model.max_attempts,
        "source_hashes": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (args.before, args.after)},
        "measurements": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        model.generate_with_usage("Reply only: ready.", max_tokens=12)
        for round_index in range(args.rounds):
            for position, (old, new) in enumerate(pairs):
                sequence = ("before", "after") if (position + round_index) % 2 == 0 else ("after", "before")
                for phase in sequence:
                    case = old if phase == "before" else new
                    call = case["model_calls"][0]
                    started = time.perf_counter()
                    row = {
                        "round": round_index + 1, "session_id": case["session_id"],
                        "phase": phase, "order": list(sequence),
                        "prompt_sha256": call["prompt_sha256"],
                    }
                    try:
                        response = model.generate_structured(
                            call["prompt"], call["response_schema"], max_tokens=call["max_tokens"])
                        row.update(
                            wall_ms=round((time.perf_counter() - started) * 1000, 2),
                            input_tokens=response.input_tokens, output_tokens=response.output_tokens,
                            raw_text=response.text, error=None,
                        )
                        data = json.loads(response.text)
                        data.pop("t", None)
                        try:
                            AssistanceDraft.model_validate(data)
                            row["schema_valid"] = True
                        except ValueError:
                            row["schema_valid"] = False
                    except Exception as error:
                        row.update(wall_ms=round((time.perf_counter() - started) * 1000, 2),
                                   error=type(error).__name__, schema_valid=False,
                                   input_tokens=None, output_tokens=None)
                    report["measurements"].append(row)
                    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({
                    "round": round_index + 1, "session_id": new["session_id"],
                    "order": sequence,
                    "times": [x["wall_ms"] for x in report["measurements"][-2:]],
                }, ensure_ascii=True), flush=True)
    finally:
        model.close()
        report["ended_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        groups = {}
        for phase in ("before", "after"):
            rows = [row for row in report["measurements"] if row["phase"] == phase]
            times = [row["wall_ms"] for row in rows]
            groups[phase] = {
                "n": len(rows), "schema_valid_n": sum(row["schema_valid"] for row in rows),
                "error_n": sum(row["error"] is not None for row in rows),
                "median_ms": statistics.median(times) if times else None,
                "sample_p95_ms": percentile(times, .95), "max_ms": max(times, default=None),
                "input_tokens": sum(row["input_tokens"] or 0 for row in rows),
                "output_tokens": sum(row["output_tokens"] or 0 for row in rows),
            }
        report["summary"] = groups
        report["capture_complete"] = len(report["measurements"]) == args.rounds * len(pairs) * 2
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=True))


if __name__ == "__main__":
    main()
