"""Test a shorter prompt off the live path; retain first passes and protected records."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from evaluation.capture_precheck_cases import RecordedQwen, digest, read_protected_records
from evaluation.evaluate_model_emotion_protocol import NoKnowledge
from src.agents.assist_agent import AssistAgent


class CompactAssistanceTrial(AssistAgent):
    prompt_version = "trial-v8-compact-boundaries-1"

    @staticmethod
    def build_prompt(context: dict, message: str, session_id: str, signals: dict) -> str:
        original = AssistAgent.build_prompt(context, message, session_id, signals)
        body = original.split("\n\n请严格只输出JSON：", 1)[0]
        return (
            body + "\n\n请严格只输出JSON："
            + ("t=当前主意图," if signals["intent_confidence"] < .90 else "")
            + "s=摘要60字,e=基础情绪,r=风险,i=来源ID,m=待核,a=回复100字,n=下一步30字。"
            "r≥rule_risk；i限输入ID。e按原话：责备/不满angry，焦急/担忧fearful，失望sad，"
            "满意happy，仅咨询/礼貌neutral；规则提示非答案。"
            "自述/历史承诺不作后台事实；历史未知写待核。"
            "按service_focus回应具体困扰并给核查；沿用已知，内部凭证由客服查。"
            "不得写我们正在核实、已登记/受理/退款/补发/安排或保证时效。"
            "无approved_knowledge不答成分/功效/政策/尾款，不诊断、猜原因或据肤质推荐。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emotion", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or (not args.emotion and args.input is None):
        raise ValueError("Require a new output path and saved input or --emotion.")
    db = ROOT / "data/runtime/evaluation.sqlite"
    pack = ROOT / "evaluation/holdout_v2/annotation_pack.json"
    before = read_protected_records(db)[0]
    pack_before = hashlib.sha256(pack.read_bytes()).hexdigest()
    load_dotenv(ROOT / ".env")
    model = RecordedQwen()
    if model.provider != "ollama":
        model.close()
        raise ValueError("Explicit loopback model only.")
    agent = CompactAssistanceTrial(model, NoKnowledge())
    if args.emotion:
        protocol = json.loads((ROOT / "evaluation/emotion_protocol_20261013.json").read_text(encoding="utf-8"))
        rows = [{
            "session_id": f"{group}-{index}", "buyer_message": item["text"],
            "expected_basic": item["basic"], "group": group,
            "input_context": {
                "analysis_point": f"{group}-{index}", "analysis_at": "2026-10-13 12:00:00",
                "analysis_mode": "replay", "messages": [], "evidence": [],
            },
        } for group in ("development", "validation")
            for index, item in enumerate(protocol[group], 1)]
        source = {"model": model.model, "analysis_mode": "replay"}
    else:
        source = json.loads(args.input.read_text(encoding="utf-8"))
        rows = source["cases"]
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(), "capture_state": "running",
        "scope": "Off-path short-prompt experiment; not independent accuracy or production release",
        "prompt_version": agent.prompt_version, "model": model.model, "analysis_mode": "replay",
        "human_review_completed": False, "human_efficiency_measured": False,
        "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest() if args.input else None,
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for row in rows:
            context, message = row["input_context"], row["buyer_message"]
            identifier = row.get("session_id") or row["sample_id"]
            stamp, call_start = time.perf_counter(), len(model.calls)
            result = agent.assist(context, message, identifier)
            report["cases"].append({
                "session_id": identifier, "analysis_point": context["analysis_point"],
                "buyer_message": message, "input_context": context, "input_context_sha256": digest(context),
                "result": result, "model_calls": model.calls[call_start:],
                "wall_ms": (time.perf_counter() - stamp) * 1000, "human_decision": None,
                **({"group": row["group"], "expected_basic": row["expected_basic"],
                    "basic_match": result.get("emotion_basic_display") == row["expected_basic"]}
                   if args.emotion else {}),
            })
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(identifier + " " + result["model_status"], flush=True)
        report["capture_state"] = "complete"
    finally:
        model.close()
        after = read_protected_records(db)[0]
        report["original_human_records_unchanged"] = before == after
        report["frozen_pack_unchanged"] = pack_before == hashlib.sha256(pack.read_bytes()).hexdigest()
        report["ended_at"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["original_human_records_unchanged"] or not report["frozen_pack_unchanged"]:
        raise RuntimeError("Protected records changed.")
    print(json.dumps({
        "n": len(report["cases"]), "fallback_n": sum(
            row["result"]["model_status"] == "fallback" for row in report["cases"]),
        "basic_match_n": sum(row.get("basic_match", False) for row in report["cases"]) if args.emotion else None,
    }))


if __name__ == "__main__":
    main()
