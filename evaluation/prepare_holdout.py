"""Prepare disjoint scene-family splits; labels remain empty for human review."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.contest_data import ContestDataStore


def prepare(store: ContestDataStore) -> dict:
    """Split by scene family to keep near-identical templates in one partition."""
    sessions = store.list_sessions(limit=1000)
    families = sorted({item["scene_minor"] for item in sessions},
                      key=lambda value: hashlib.sha256(value.encode()).hexdigest())
    heldout_families = set(families[:max(1, len(families) // 3)])
    pools = {"development": [], "heldout": []}
    for item in sorted(sessions, key=lambda row: row["session_id"]):
        # No future agent message is supplied at the first buyer analysis point.
        detail = store.get_session(item["session_id"])
        choices = detail["message_choices"]
        if not choices:
            continue
        point = choices[0]["id"]
        partition = "heldout" if item["scene_minor"] in heldout_families else "development"
        context = store.get_session(item["session_id"], before_message_id=point, analysis_mode="replay")
        pools[partition].append({
            "sample_id": item["session_id"], "analysis_point": point,
            "family_for_split_only": item["scene_minor"],
            "context": store.model_context(context),
            "buyer_message": context["latest_buyer_message"],
            "human_annotation": {
                "status": "pending", "reviewer": None, "intent": None,
                "emotion": None, "risk_level": None, "expected_facts": [],
                "supporting_evidence_ids": [], "acceptable_next_action": None,
            },
        })
    return {
        "source": "contest_mock", "split_rule": "disjoint scene families / fixed SHA256 ordering",
        "metrics_status": "not_measured; no human labels supplied",
        "development": pools["development"][:20],
        "heldout": pools["heldout"][:30],
        "development_pool_size": len(pools["development"]),
        "heldout_pool_size": len(pools["heldout"]),
        "notes": "Grouping reduces template overlap; unseen scene holdout is harder than random split.",
    }


def main() -> None:
    """Create only new annotation fixtures; never overwrite filled labels."""
    output = ROOT / "evaluation" / "holdout_v2"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "annotation_pack.json"
    if path.exists():
        raise SystemExit("Annotation pack already exists; preserved without changes.")
    pack = prepare(ContestDataStore(ROOT / "data" / "contest"))
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(pack['development'])} development and {len(pack['heldout'])} heldout samples.")
    print("Human labels are pending; no accuracy score has been calculated.")


if __name__ == "__main__":
    main()
