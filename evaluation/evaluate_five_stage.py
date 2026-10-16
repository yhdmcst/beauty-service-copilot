"""Reproducible engineering protocol, optional real model calls, no runtime DB writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.assist_agent import AssistAgent
from src.agents.intent_agent import IntentAgent
from src.knowledge.service_guidance import service_focus
from src.models.qwen_wrapper import configured_model


def run(protocol: Path, model: bool = False, limit: int = 0, checkpoint: Path | None = None, resume: bool = False) -> dict:
    raw = protocol.read_bytes()
    data = json.loads(raw)
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    cases = data["cases"][:limit or None]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Protocol case IDs must be unique")
    rows = []
    source = hashlib.sha256()
    for path in sorted(list((ROOT / "src").rglob("*.py")) + list((ROOT / "data/beauty_knowledge").glob("*.json"))):
        source.update(str(path.relative_to(ROOT)).encode())
        source.update(path.read_bytes())
    execution = {"source_sha256": source.hexdigest()}
    if model:
        execution.update(model=configured_model(), provider=os.getenv("QWEN_PROVIDER", "openai"),
                         configuration_sha256=hashlib.sha256(json.dumps({key: os.getenv(key, "") for key in
                             ("QWEN_API_BASE", "QWEN_THINKING", "QWEN_TIMEOUT_SECONDS", "QWEN_MAX_ATTEMPTS")}, sort_keys=True).encode()).hexdigest())
    identity = {"protocol_sha256": hashlib.sha256(raw).hexdigest(),
                "revision": AssistAgent.prompt_version, "mode": "model" if model else "rules", "execution": execution}
    if resume and checkpoint and checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if any(saved.get(key) != value for key, value in identity.items()):
            raise ValueError("Checkpoint protocol, revision or mode mismatch")
        rows = saved["rows"]
        if [row["id"] for row in rows] != [case["id"] for case in cases[:len(rows)]] or len(rows) > len(cases):
            raise ValueError("Checkpoint cases do not match requested run")
    def save():
        if checkpoint:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
            temporary.write_text(json.dumps({**identity, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(checkpoint)
    classifier = IntentAgent()
    assistant = AssistAgent(enable_evidence_routes=False) if model else None
    for case in cases[len(rows):]:
        started = time.perf_counter()
        if assistant:
            context = {"session_id": "ENGINEERING", "analysis_point": "point-1",
                       "analysis_mode": "replay", "analysis_at": "2026-06-08 11:00:00",
                       "messages": [], "evidence": [], "service_history": {}}
            result = assistant.assist(context, case["message"], "ENGINEERING")
            intent, focus = result["intent"], result["service_focus"]["category"]
        else:
            intent = classifier.classify(case["message"])["intent_name"]
            focus = service_focus(case["message"], intent)["category"]
            result = {}
        rows.append({**case, "actual_intent": intent, "actual_focus": focus,
                     "intent_match": intent == case["intent"], "focus_match": focus == case["focus"],
                     "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                     "result": result})
        save()
    times = sorted(row["elapsed_ms"] for row in rows)
    generated_times = sorted(row["elapsed_ms"] for row in rows if row["result"].get("model_status") in {"model", "local_qwen"})
    return {"scope": data["scope"], "protocol_sha256": hashlib.sha256(raw).hexdigest(),
            "execution": execution,
            "revision": AssistAgent.prompt_version, "mode": "model" if model else "rules",
            "n": len(rows), "intent_matches": sum(row["intent_match"] for row in rows),
            "focus_matches": sum(row["focus_match"] for row in rows),
            "fallback_n": sum(row["result"].get("model_status") == "fallback" for row in rows),
            "total_tokens": sum(sum(row["result"].get("usage", {}).values()) for row in rows),
            "p50_ms": statistics.median(times) if times else None,
            "max_ms": max(times) if times else None,
            "generated_n": len(generated_times),
            "usage_unavailable_n": sum(row["result"].get("model_status") == "fallback" for row in rows),
            "final_checked_n": sum("final_validation_flags" in row["result"] for row in rows),
            "generated_p50_ms": statistics.median(generated_times) if generated_times else None,
            "final_flagged_n": sum(bool(row["result"].get("final_validation_flags")) for row in rows),
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evaluation/five_stage_protocol.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true", help="Resume matching per-case checkpoint")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("limit must be nonnegative")
    if args.model:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    result = run(args.protocol, args.model, args.limit,
                 args.output.with_suffix(args.output.suffix + ".checkpoint"), args.resume)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
