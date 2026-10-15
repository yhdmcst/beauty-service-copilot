"""Keep author clarification separate from click-inferred origin and raw labels."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ORIGIN_PATH = Path(__file__).resolve().parent / "results" / "annotation_origin_clarification.json"


def provenance_report(rows: list[dict], path: Path = ORIGIN_PATH) -> dict:
    """Use a declared human origin only for the exact saved label versions stated."""
    raw = Counter(row.get("label_source", "legacy_unspecified") for row in rows)
    effective = Counter()
    matched = []
    clarification = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    versions = (clarification or {}).get("label_versions", {})
    for row in rows:
        declared = (
            clarification
            and clarification.get("declared_origin") == "human_judgment"
            and versions.get(row["sample_id"]) == row.get("updated_at")
        )
        if declared:
            effective["human"] += 1
            matched.append(row["sample_id"])
        else:
            effective[row.get("label_source", "legacy_unspecified")] += 1
    return {
        "raw_label_sources": dict(raw),
        "effective_label_sources": dict(effective),
        "declared_human_n": len(matched),
        "declared_human_sample_ids": sorted(matched),
        "legacy_suggestion_click_inferred_n": raw.get("assisted_human", 0),
        "evidence_type": "user_statement_bound_to_saved_label_versions" if matched else "raw_saved_metadata",
        "statement": clarification.get("statement") if matched else None,
        "independent_blind_annotation_status": "not_verified",
        "warning": "Click history is not evidence of adopting a suggestion; human judgment is not proof of blind independence.",
    }
