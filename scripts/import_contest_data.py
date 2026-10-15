"""Import the supplied contest workbook into a portable JSON demo snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.contest_data import export_tables, load_workbook

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "contest_materials" / "赛题 1：数据共情者-业务数据.xlsx"


def main() -> None:
    """Import only local contest data and preserve its synthetic-data warning."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "contest")
    args = parser.parse_args()
    if not args.source.exists():
        raise SystemExit(f"Workbook not found: {args.source}")
    tables = load_workbook(args.source)
    output = export_tables(tables, args.output)
    print(f"Imported {sum(len(rows) for rows in tables.values())} records into {output}")
    print("WARNING: source data is synthetic contest MOCK data, not production data.")


if __name__ == "__main__":
    main()
