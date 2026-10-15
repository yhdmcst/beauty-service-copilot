"""Keep basic and scenario emotion checks separate and retain every disagreement."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.emotion_agent import EmotionAgent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "evaluation/emotion_protocol_20261013.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Retain previous measurements.")
    raw = args.protocol.read_bytes()
    data = json.loads(raw)
    groups = {}
    agent = EmotionAgent()
    for name in ("development", "validation"):
        rows = []
        for item in data[name]:
            result = agent.analyze(item["text"])
            rows.append({
                **item, "actual_basic": result["basic_emotion"],
                "actual_scene": result["special_emotion"], "valence": result["valence"],
                "basic_match": item["basic"] == result["basic_emotion"],
                "scene_match": item["scene"] == result["special_emotion"],
            })
        groups[name] = {
            "n": len(rows), "basic_match_n": sum(row["basic_match"] for row in rows),
            "scene_match_n": sum(row["scene_match"] for row in rows), "cases": rows,
        }
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "scope": data["scope"],
        "human_gold": False, "model_called": False, "groups": groups,
        "protocol_sha256": hashlib.sha256(raw).hexdigest(),
        "emotion_implementation_sha256": hashlib.sha256((ROOT / "src/agents/emotion_agent.py").read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in group.items() if key != "cases"}
                      for name, group in groups.items()}, ensure_ascii=True))


if __name__ == "__main__":
    main()
