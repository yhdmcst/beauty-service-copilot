"""Evaluate intent and service-focus agreement using a fixed engineering protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.assist_agent import AssistAgent
from src.agents.intent_agent import IntentAgent
from src.knowledge.service_guidance import service_focus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evaluation/request_focus_protocol_20261013.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Previous evaluation retained; choose a new path.")
    raw = args.protocol.read_bytes()
    protocol = json.loads(raw)
    groups = {}
    agent = IntentAgent()
    for name in ("development", "validation"):
        rows = []
        for item in protocol[name]:
            intent = agent.classify(item["text"])["intent_name"]
            focus = service_focus(item["text"], intent)["category"]
            rows.append({**item, "actual_intent": intent, "actual_focus": focus,
                         "intent_matches": intent == item["intent"],
                         "focus_matches": focus == item["focus"]})
        groups[name] = {
            "n": len(rows), "intent_match_n": sum(row["intent_matches"] for row in rows),
            "focus_match_n": sum(row["focus_matches"] for row in rows), "cases": rows,
        }
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "scope": protocol["scope"], "human_gold": False, "model_called": False,
        "revision": AssistAgent.prompt_version,
        "protocol_sha256": hashlib.sha256(raw).hexdigest(),
        "groups": groups,
        "implementation_sha256": {
            str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (Path("src/agents/intent_agent.py"), Path("src/knowledge/service_guidance.py"),
                         Path("src/utils/service_requests.py")) if (ROOT / path).exists()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in group.items() if key != "cases"}
                      for name, group in groups.items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
