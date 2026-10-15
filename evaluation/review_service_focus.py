"""Record new-wording reproductions without treating them as independent human labels."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.capture_precheck_cases import read_protected_records
from src.agents.assist_agent import AssistAgent
from src.agents.intent_agent import IntentAgent
from src.knowledge.service_guidance import service_focus

CASES = (
    ("不改地址了，我要退款", "refund_request", "refund_status_or_amount"),
    ("不查赠品，只问发货了没", "logistics_query", "shipment_query"),
    ("不怀疑假货，只是色号发错了", "quality_issue", "sku_mismatch"),
    ("不用退货退款，只核对发货时间", "logistics_query", "shipment_query"),
    ("没有申请退款，只想改地址", "order_query", "address_change"),
    ("我的退款还没到账", "refund_request", "refund_status_or_amount"),
    ("收到货没有赠品，帮查是否分包", "activity_inquiry", "promotion_or_gift"),
    ("用了面霜后脸肿了，想处理售后", "allergy_reaction", "adverse_reaction_report"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Retain previous reports; use another path.")
    before, _ = read_protected_records(ROOT / "data/runtime/evaluation.sqlite")
    agent = IntentAgent()
    rows = []
    for message, expected_intent, expected_focus in CASES:
        intent = agent.classify(message)["intent_name"]
        focus = service_focus(message, intent)["category"]
        rows.append({
            "message": message, "actual_intent": intent, "actual_focus": focus,
            "engineering_expected_intent": expected_intent,
            "engineering_expected_focus": expected_focus,
            "intent_matches": intent == expected_intent,
            "focus_matches": focus == expected_focus,
        })
    after, _ = read_protected_records(ROOT / "data/runtime/evaluation.sqlite")
    assert before == after
    report = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "revision": AssistAgent.prompt_version,
        "scope": "selected development counterexamples and controls; not random sampling or independent human gold",
        "release_code_changed": False, "original_human_records_unchanged": True,
        "model_called": False, "n": len(rows),
        "intent_mismatch_n": sum(not row["intent_matches"] for row in rows),
        "focus_mismatch_n": sum(not row["focus_matches"] for row in rows),
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "revision", "n", "intent_mismatch_n", "focus_mismatch_n",
        "release_code_changed", "original_human_records_unchanged")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
