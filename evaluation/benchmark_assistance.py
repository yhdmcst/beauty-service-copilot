"""Repeatable localhost measurements; no human labels or efficiency trials are written."""

from __future__ import annotations

import argparse
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
from src.agents.assist_agent import AssistAgent
from src.data.contest_data import ContestDataStore
from src.models.qwen_wrapper import QwenWrapper
from src.ops.case_store import CaseStore
from src.orchestration.workbench_workflow import WorkbenchWorkflow

CASES = [
    ("S00381", "请核对订单实付和退款工单金额，不要把待审核说成退款完成。"),
    ("S00107", "请核实改地址和物流处理进度，不保证拦截成功。"),
    ("S00029", "请核实订单金额和退运费记录，金额不要混用。"),
    ("S00154", "请整理当前服务问题和后续需要核实的事项。"),
    ("S00082", "请核实当前不适记录及后续处理状态。"),
]


class BaselineModel:
    """Use the same provider without schema, as in the previous workbench."""

    provider = "ollama"

    def __init__(self, model: QwenWrapper) -> None:
        self.delegate, self.model = model, model.model

    def generate_with_usage(self, prompt: str, max_tokens: int = 420):
        return self.delegate.generate_with_usage(prompt, max_tokens=420)


class BaselineAgent(AssistAgent):
    """Reconstruct the previous verbose prompt for a reproducible ablation."""
    prompt_version = "verbose-v4-reconstructed"

    @staticmethod
    def build_prompt(context, message, session_id, signals):
        payload = {
            "session_id": session_id, "buyer_message": message[:500],
            "signals": {
                "intent": signals["intent"],
                "emotion": signals.get("special_emotion") or signals["emotion_basic"],
                "rule_risk": signals["risk_level_rule"],
                "rule_triggers": signals["risk_triggers"],
                "emotion_trend": signals["emotion_trend"],
                "service_risk_counts": signals["service_risk_counts"],
            },
            "context": ContestDataStore.model_context(context),
            "knowledge": {
                "gate_reason": signals["knowledge"]["reason"],
                "gate_confidence": signals["knowledge"]["confidence"],
                "verified_context": signals["knowledge"]["verified_context"],
            },
        }
        return (
            "你是人工美妆客服的副驾，只提供建议，不执行任何业务操作。\n"
            "以下是赛题提供的虚构 MOCK 数据，仅用于演示；不得把它说成真实生产数据。\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n\n请严格只输出 JSON 对象，字段为：\n"
            "summary（100字内服务轨迹摘要）、emotion（焦急/失望/中性/满意/担忧/其他）、"
            "risk_level（低/中/高/紧急）、evidence_ids（只能填写输入中出现的订单号或工单号）、"
            "missing_info（需要客服补充核实的事项数组）、"
            "suggested_reply（150字内、先共情后事实、给客服审核的草稿）、"
            "next_action（不超过40字的建议操作）。"
            "模型只能引用输入里的证据；如果是历史快照，必须说明还需要客服核实最新状态。"
            "知识检索结果只有在 gate_reason 为 supported 且 verified_context 非空时才可作为事实依据；"
            "否则只能把知识区视为待人工核验提示，不得将其写成已确认的商品或平台政策。"
            "禁止承诺已退款、已补发、已加急、保证到货或任何医疗结论。"
        )


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank sample percentile; not an online service guarantee."""
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "results")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    model = QwenWrapper()
    if model.provider != "ollama":
        raise SystemExit("This benchmark permits localhost Ollama only.")
    started = time.perf_counter()
    warmup = model.generate_with_usage("仅回复：准备完成。", max_tokens=16)
    warmup_ms = (time.perf_counter() - started) * 1000
    data, cases, events = ContestDataStore(ROOT / "data" / "contest"), CaseStore(), []
    agent = BaselineAgent(BaselineModel(model)) if args.phase == "before" else AssistAgent(model)
    flow = WorkbenchWorkflow(data, agent, cases, events.append)
    rows = []
    for session, message in CASES:
        started = time.perf_counter()
        result = flow.run(session, message)
        row = {
            "session": session, "message": message,
            "wall_ms": round((time.perf_counter() - started) * 1000, 2),
            "node_ms": result.get("latency_ms"),
            "model_status": result["model_status"],
            "usage": result["usage"], "risk": result["risk_level"],
            "flags": result["validation_flags"],
            "reply": result["suggested_reply"], "summary": result["summary"],
            "trace": result["trace"],
            "prompt_stats": result.get("prompt_stats"),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    started = time.perf_counter()
    repeated = flow.run(*CASES[0])
    repeat_ms = (time.perf_counter() - started) * 1000
    times = [row["wall_ms"] for row in rows]
    report = {
        "date": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "five fixed contest MOCK snapshot cases, sequential warmed localhost; not human quality/efficiency",
        "phase": args.phase, "model": model.model, "n": len(rows),
        "comparison": "reconstructed verbose V4 prompt/unconstrained vs compact V5/schema; validation evolves across runs, not a single-factor ablation",
        "warmup_ms": round(warmup_ms, 2),
        "warmup_usage": {"input_tokens": warmup.input_tokens, "output_tokens": warmup.output_tokens},
        "p50_ms": round(statistics.median(times), 2),
        "p95_ms": round(percentile(times, .95), 2),
        "input_tokens": sum(row["usage"]["input_tokens"] for row in rows),
        "output_tokens": sum(row["usage"]["output_tokens"] for row in rows),
        "fallback_count": sum(row["model_status"] == "fallback" for row in rows),
        "repeat": {"ms": round(repeat_ms, 2), "cache_hit": repeated["cache_hit"],
                   "usage": repeated["usage"]},
        "cases": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"performance_{args.phase}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cases.close()
    model.close()
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
