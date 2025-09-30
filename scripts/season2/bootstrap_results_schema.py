#!/usr/bin/env python3
"""Ensure the Season 2 results database schema exists."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.season2 import Season2ResultsStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        dest="database",
        type=Path,
        help="Path to the results database (defaults to PANENKA_RESULTS_DB or app/season2/season2_results.sqlite3)",
    )
    parser.add_argument(
        "--no-seed",
        dest="seed",
        action="store_false",
        help="Skip inserting baseline season records",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = Season2ResultsStore(
        db_path=str(args.database) if args.database else None,
        enable_season_seed=args.seed,
    )
    store.ensure_schema()
    print(f"Ensured Season 2 results schema at {store.db_path}")


if __name__ == "__main__":
    main()
