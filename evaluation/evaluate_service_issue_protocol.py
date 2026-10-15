"""Separate intent, practical focus and basic emotion on saved engineering wording."""

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
from src.agents.emotion_agent import EmotionAgent
from src.knowledge.service_guidance import service_focus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evaluation/service_issue_protocol_20261014.json")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Retain prior protocol outputs.")
    path = args.protocol
    raw = path.read_bytes()
    protocol = json.loads(raw)
    groups = {}
    for group in ("development", "validation"):
        rows = []
        for item in protocol[group]:
            intent = IntentAgent().classify(item["text"])["intent_name"]
            actual = {
                "intent": intent, "focus": service_focus(item["text"], intent)["category"],
                "basic": EmotionAgent().analyze(item["text"])["basic_emotion"],
            }
            rows.append({
                **item, "actual": actual,
                "matches": {field: item[field] == value for field, value in actual.items()},
            })
        groups[group] = {
            "n": len(rows), "metrics": {
                field: sum(row["matches"][field] for row in rows)
                for field in ("intent", "focus", "basic")
            }, "cases": rows,
        }
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "scope": protocol["scope"],
        "human_gold": False, "model_called": False, "revision": AssistAgent.prompt_version,
        "protocol_sha256": hashlib.sha256(raw).hexdigest(), "groups": groups,
        "implementation_sha256": {
            str(file): hashlib.sha256((ROOT / file).read_bytes()).hexdigest()
            for file in (
                Path("src/agents/intent_agent.py"), Path("src/agents/emotion_agent.py"),
                Path("src/knowledge/service_guidance.py"), Path("src/utils/service_requests.py"),
                Path("src/utils/service_issue_cues.py"),
            ) if (ROOT / file).is_file()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: {"n": group["n"], "metrics": group["metrics"]}
                      for name, group in groups.items()}))


if __name__ == "__main__":
    main()
