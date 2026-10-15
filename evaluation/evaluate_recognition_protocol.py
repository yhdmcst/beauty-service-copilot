"""Evaluate an engineering-defined wording protocol, not new human annotations."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.emotion_agent import EmotionAgent
from src.agents.intent_agent import IntentAgent


def evaluate(protocol: dict) -> dict:
    intent, emotion = IntentAgent(), EmotionAgent()
    groups = {}
    for name in ("development", "validation"):
        items = []
        for row in protocol[name]:
            intent_result = intent.classify(row["text"])
            emotion_result = emotion.analyze(row["text"])
            predicted = {
                "intent": intent_result["intent_name"],
                "basic": emotion_result["basic_emotion"],
                "scene": emotion_result["special_emotion"],
            }
            items.append({
                "text": row["text"], "expected": {key: row[key] for key in predicted},
                "predicted": predicted,
                "matches": {key: row[key] == predicted[key] for key in predicted},
            })
        groups[name] = {
            "n": len(items),
            "metrics": {
                key: {"correct": sum(item["matches"][key] for item in items),
                      "n": len(items),
                      "rate": sum(item["matches"][key] for item in items) / len(items)}
                for key in ("intent", "basic", "scene")
            },
            "cases": items,
        }
    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "engineering-defined wording checks; not independent human/customer accuracy",
        "human_gold": False, "groups": groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path,
                        default=ROOT / "evaluation/recognition_protocol_20261009.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Previous results must be retained.")
    data = args.protocol.read_bytes()
    report = evaluate(json.loads(data))
    report["protocol_sha256"] = hashlib.sha256(data).hexdigest()
    report["implementation_sha256"] = {
        str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in (Path("src/agents/intent_agent.py"), Path("src/agents/emotion_agent.py"),
                     Path("src/risk/beauty_risk_rules.py"), Path("src/utils/service_requests.py"))
        if (ROOT / path).exists()
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: {"n": group["n"], "metrics": group["metrics"]}
                      for name, group in report["groups"].items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
