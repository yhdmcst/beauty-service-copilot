"""Generate review-only annotation suggestions without modifying human labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.evaluation_center import DEFAULT_DB, FrozenAnnotationAgent


def main() -> None:
    store = FrozenAnnotationAgent(DEFAULT_DB)
    paths = {
        "heldout": store.export_suggestions("heldout"),
        "development": store.export_suggestions("development"),
    }
    print(json.dumps({key: str(path) for key, path in paths.items()},
                     ensure_ascii=False, indent=2))
    store.close()


if __name__ == "__main__":
    main()
