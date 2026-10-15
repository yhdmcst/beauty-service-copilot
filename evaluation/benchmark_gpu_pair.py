"""Compare two loopback inference backends using identical captured requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.qwen_wrapper import is_loopback_url
from src.agents.assist_agent import AssistanceDraft


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", default="http://127.0.0.1:11434")
    parser.add_argument("--gpu", default="http://127.0.0.1:11435")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Keep previous benchmarks.")
    for base in (args.cpu, args.gpu):
        if not is_loopback_url(base):
            raise ValueError("Only loopback backend comparison is permitted.")
    source = json.loads(args.input.read_text(encoding="utf-8"))
    chosen = [case for case in source["cases"] if case["model_calls"]][:3]
    assert len(chosen) == 3
    model = source["model"]
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scope": "three fixed captured cases, alternating order, one local CPU and GPU backend; not production SLA",
        "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "model": model, "warmup": [], "attempts": [], "human_review": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with httpx.Client(trust_env=False, timeout=90) as client:
        for kind, base in (("cpu", args.cpu), ("gpu", args.gpu)):
            started = time.perf_counter()
            response = client.post(base + "/api/generate", json={
                "model": model, "prompt": "Reply ready.", "stream": False,
                "think": False, "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 12, "num_ctx": 4096},
            })
            response.raise_for_status()
            report["warmup"].append({
                "kind": kind, "wall_ms": (time.perf_counter() - started) * 1000,
                "runtime": client.get(base + "/api/ps").json(),
            })
        for round_index in range(2):
            for index, case in enumerate(chosen):
                order = (("cpu", args.cpu), ("gpu", args.gpu))
                if (round_index + index) % 2:
                    order = tuple(reversed(order))
                call = case["model_calls"][0]
                schema = call["response_schema"]
                for kind, base in order:
                    row = {
                        "kind": kind, "round": round_index + 1, "session_id": case["session_id"],
                        "prompt_sha256": call["prompt_sha256"], "input_tokens": None, "output_tokens": None,
                    }
                    started = time.perf_counter()
                    try:
                        response = client.post(base + "/v1/chat/completions", json={
                            "model": model, "messages": [{"role": "user", "content": call["prompt"]}],
                            "temperature": 0, "reasoning_effort": "none", "max_tokens": call["max_tokens"],
                            "response_format": {"type": "json_schema",
                                                "json_schema": {"name": "assistance", "strict": True, "schema": schema}},
                        })
                        response.raise_for_status()
                        payload = response.json()
                        raw = payload["choices"][0]["message"]["content"]
                        parsed = json.loads(raw)
                        if "t" in schema.get("required", []):
                            assert parsed.get("t") in schema["properties"]["t"]["enum"]
                        parsed.pop("t", None)
                        validated = AssistanceDraft.model_validate(parsed)
                        assert validated.emotion in schema["properties"]["e"]["enum"]
                        row.update(
                            schema_valid=True, raw_text=raw,
                            input_tokens=payload["usage"]["prompt_tokens"],
                            output_tokens=payload["usage"]["completion_tokens"],
                        )
                    except Exception as error:
                        row.update(schema_valid=False, error_type=type(error).__name__)
                    row["wall_ms"] = (time.perf_counter() - started) * 1000
                    report["attempts"].append(row)
                    save()
                    print(f"{kind} {case['session_id']} {row['wall_ms']:.0f}ms valid={row['schema_valid']}", flush=True)
        report["runtime_after"] = {
            kind: client.get(base + "/api/ps").json() for kind, base in
            (("cpu", args.cpu), ("gpu", args.gpu))}
    import statistics

    report["summary"] = {
        kind: {
            "n": len(rows), "schema_valid_n": sum(row["schema_valid"] for row in rows),
            "median_ms": statistics.median(row["wall_ms"] for row in rows),
            "total_tokens": sum((row["input_tokens"] or 0) + (row["output_tokens"] or 0) for row in rows),
        } for kind in ("cpu", "gpu")
        for rows in [[row for row in report["attempts"] if row["kind"] == kind]]
    }
    report["ended_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps(report["summary"], ensure_ascii=True))


if __name__ == "__main__":
    main()
