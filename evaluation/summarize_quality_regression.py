"""Summarize saved before/after drafts without inventing human quality judgments."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.knowledge.business_claims import check_claims
from src.knowledge.service_guidance import review_guidance, service_focus


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze_cases(report: dict) -> list[dict]:
    rows = []
    for case in report["cases"]:
        draft, context = case["result"], case["input_context"]
        claims = []
        for field in ("summary", "suggested_reply", "next_action"):
            result = check_claims(
                draft[field], context["evidence"], draft["evidence_ids"],
                source_text=case["buyer_message"], analysis_at=context["analysis_at"])
            claims.extend({**check, "field": field} for check in result["checks"])
        unsupported = [check for check in claims if check["status"] == "unsupported"]
        operational = review_guidance(
            draft, context, case["buyer_message"],
            service_focus(case["buyer_message"], draft["intent"]))
        rows.append({
            "session_id": case["session_id"],
            "analysis_point": case["analysis_point"],
            "claim_issues": unsupported,
            "service_issues": operational["issues"],
            "raw_flags": draft.get("validation_flags", []),
            "adjustment_n": len(draft.get("quality_adjustments", [])),
            "wall_ms": case["wall_ms"],
            "input_tokens": draft["usage"]["input_tokens"],
            "output_tokens": draft["usage"]["output_tokens"],
            "model_status": draft["model_status"],
            "summary": draft["summary"],
            "reply": draft["suggested_reply"],
            "next_action": draft["next_action"],
        })
    return rows


def aggregate(rows: list[dict]) -> dict:
    generation = [row["wall_ms"] for row in rows if row["model_status"] in {"local_qwen", "model"}]
    return {
        "n": len(rows),
        "claim_issue_case_n": sum(bool(row["claim_issues"]) for row in rows),
        "service_issue_case_n": sum(bool(row["service_issues"]) for row in rows),
        "raw_flagged_case_n": sum(bool(row["raw_flags"]) for row in rows),
        "adjusted_case_n": sum(row["adjustment_n"] > 0 for row in rows),
        "adjustment_n": sum(row["adjustment_n"] for row in rows),
        "model_fallback_n": sum(row["model_status"] == "fallback" for row in rows),
        "rule_evidence_n": sum(row["model_status"] == "rule_evidence" for row in rows),
        "generation_n": len(generation),
        "generation_median_wall_ms": statistics.median(generation) if generation else None,
        "median_wall_ms": statistics.median(row["wall_ms"] for row in rows) if rows else None,
        "max_wall_ms": max((row["wall_ms"] for row in rows), default=None),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "total_tokens": sum(row["input_tokens"] + row["output_tokens"] for row in rows),
    }


def summarize(before: dict, after: dict) -> dict:
    old = {row["session_id"]: row for row in before["cases"]}
    new = {row["session_id"]: row for row in after["cases"]}
    if not old or len(old) != len(before["cases"]) or len(new) != len(after["cases"]) or old.keys() != new.keys():
        raise ValueError("Comparison requires the same nonempty unique case IDs.")
    if before["model"] != after["model"] or before["analysis_mode"] != after["analysis_mode"]:
        raise ValueError("Model and analysis mode must match.")
    for session_id, case in old.items():
        compared = new[session_id]
        if any(case[field] != compared[field] for field in (
            "analysis_point", "buyer_message", "input_context_sha256")):
            raise ValueError(f"Context or analysis point differs: {session_id}")
    old_rows, new_rows = analyze_cases(before), analyze_cases(after)
    old_stats, new_stats = aggregate(old_rows), aggregate(new_rows)
    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "same fixed MOCK cases; current rule checks on both saved outputs; not independent/human quality approval",
        "method": "one captured request per case per version, intermediate development runs retained; not a single-factor performance ablation",
        "prompt_before": before["prompt_version"], "prompt_after": after["prompt_version"],
        "model": after["model"], "before": old_stats, "after": new_stats,
        "input_token_change_pct": (
            (new_stats["input_tokens"] / old_stats["input_tokens"] - 1) * 100
            if old_stats["input_tokens"] else None),
        "total_token_change_pct": (
            (new_stats["total_tokens"] / old_stats["total_tokens"] - 1) * 100
            if old_stats["total_tokens"] else None),
        "cases_before": old_rows, "cases_after": new_rows,
        "human_quality_rate": None, "human_efficiency_improvement": None,
        "warning": "No rule issue is not proof of semantic correctness; changed wording is not a measured improvement by itself.",
    }


def markdown(report: dict) -> str:
    old, new = report["before"], report["after"]
    lines = [
        "# 主线优化与复测", "",
        f"记录时间：{report['generated_at']}。数据为赛题MOCK，同案例修复回归，不是新独立盲测或人工效率试验。", "",
        "## 测量结果", "",
        "| 指标 | 原首轮 | 当前版本 |",
        "| --- | ---: | ---: |",
        f"| 同案例数量 | {old['n']} | {new['n']} |",
        f"| 当前声明校验检出的案例数 | {old['claim_issue_case_n']} | {new['claim_issue_case_n']} |",
        f"| 当前服务行为检查检出的案例数 | {old['service_issue_case_n']} | {new['service_issue_case_n']} |",
        f"| 模型不可用降级 | {old['model_fallback_n']} | {new['model_fallback_n']} |",
        f"| 输入Token | {old['input_tokens']} | {new['input_tokens']} |",
        f"| 输出Token | {old['output_tokens']} | {new['output_tokens']} |",
        f"| 本机顺序运行中位耗时/秒 | {old['median_wall_ms']/1000:.2f} | {new['median_wall_ms']/1000:.2f} |",
        f"| 本机样本最大耗时/秒 | {old['max_wall_ms']/1000:.2f} | {new['max_wall_ms']/1000:.2f} |", "",
        f"输入Token变化{report['input_token_change_pct']:+.2f}%，总Token变化{report['total_token_change_pct']:+.2f}%。"
        + ("本组Token实测减少，提示/协议/路由同时变化，不作单因素归因。"
           if report["total_token_change_pct"] < 0
           else "新增质量约束存在开销，本组不声称Token下降。")
        + "不同运行时段的耗时差异不解释成确定提速。", "",
        f"当前有{new['adjusted_case_n']}条、{new['adjustment_n']}处修正留证。"
        "原模型触发、修正前后及最终校验分别保存，校验修正不需要第二次模型调用；精确缓存命中不产生新Token。", "",
        "## 结果边界", "",
        "- 两版本使用相同消息、分析时点和上下文；规则应用于双方原保存输出。",
        "- 本轮开发期间的各次中间复测保留，不选取每条最好结果拼成一组。",
        "- 原始人工标注、计时、冻结模板和首轮输出不覆写。",
        "- 无规则问题不等于通用准确率100%，同一规则复查也不是独立人工审核。",
        "- 服务意图和情绪原规则指标未被本次改稿换算成更高准确率。",
        "- 仅描述本机系统时延与Token，不报告人工节省、云账单或生产并发保证。", "",
        "## 原稿与当前建议", "",
    ]
    originals = {row["session_id"]: row for row in report["cases_before"]}
    for row in report["cases_after"]:
        prior = originals[row["session_id"]]
        lines.extend([
            f"### {row['session_id']}", "",
            f"- 原摘要：{prior['summary']}", f"- 当前摘要：{row['summary']}",
            f"- 原回复：{prior['reply']}", f"- 当前回复：{row['reply']}",
            f"- 原下一步：{prior['next_action']}", f"- 当前下一步：{row['next_action']}",
            f"- 自动复检：声明问题{len(row['claim_issues'])}项；服务问题{len(row['service_issues'])}项；修正{row['adjustment_n']}处。", "",
        ])
    lines.extend([
        "## 接下来", "",
        "主体优化与回归结果可用于展示；PPT与实际使用视频仍需定稿。"
        "人工效率对照可选，缺少有效记录就不报告人工提效数字，不作为本项目收尾硬门槛。", "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.markdown.exists():
        raise FileExistsError("Use new report paths; previous evidence is not overwritten.")
    after = json.loads(args.after.read_text(encoding="utf-8"))
    if not after.get("implementation_sha256"):
        raise ValueError("After report must include implementation hashes.")
    for filename, expected in after["implementation_sha256"].items():
        if file_hash(ROOT / filename) != expected:
            raise ValueError(f"Code changed since capture: {filename}")
    report = summarize(json.loads(args.before.read_text(encoding="utf-8")), after)
    report["source_versions"] = {
        "before": {"path": str(args.before), "sha256": file_hash(args.before)},
        "after": {"path": str(args.after), "sha256": file_hash(args.after)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "before", "after", "input_token_change_pct", "total_token_change_pct")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
