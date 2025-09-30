"""Compile historical fight results for seasons 1 and 2 into a SQLite bundle."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.historical_results_loader import (
    DEFAULT_SEASON1_FIXTURE,
    DEFAULT_SEASON2_DATA_ROOT,
    DEFAULT_SEASON2_MANIFEST,
    build_historical_database,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season1-json",
        type=Path,
        default=DEFAULT_SEASON1_FIXTURE,
        help="Path to the Season 1 tour results fixture.",
    )
    parser.add_argument(
        "--season2-data-root",
        type=Path,
        default=DEFAULT_SEASON2_DATA_ROOT,
        help="Directory with Season 2 CSV tour snapshots.",
    )
    parser.add_argument(
        "--season2-manifest",
        type=Path,
        default=DEFAULT_SEASON2_MANIFEST,
        help="Manifest describing Season 2 worksheets.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("app/static/data/historical_results.sqlite3"),
        help="Destination SQLite database path.",
    )
    return parser


def _format_summary(summary: dict[str, dict[str, int]]) -> str:
    lines = ["Historical results database generated:"]
    for season, stats in sorted(summary.items()):
        lines.append(f"  {season}:")
        for key, value in sorted(stats.items()):
            lines.append(f"    {key.replace('_', ' ')}: {value}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    summary = build_historical_database(
        season1_json=args.season1_json,
        season2_data_root=args.season2_data_root,
        season2_manifest=args.season2_manifest,
        output=args.output,
    )
    print(_format_summary(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI helper
    raise SystemExit(main())
