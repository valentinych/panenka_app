"""CLI utility for verifying Season 2 import integrity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.season2 import Season2ResultsStore, Season2ResultsVerifier


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to the Season 2 results database. Defaults to the store's configured path.",
    )
    parser.add_argument(
        "--expected-questions",
        type=int,
        default=5,
        help="Expected number of questions per fight (defaults to 5).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the verification report as indented JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    store = Season2ResultsStore(
        db_path=str(args.db_path) if args.db_path else None,
        enable_season_seed=False,
    )
    verifier = Season2ResultsVerifier(
        store=store,
        expected_questions_per_fight=args.expected_questions,
    )
    report = verifier.verify()

    payload = report.as_dict()
    if args.pretty:
        output = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        output = json.dumps(payload, ensure_ascii=False)
    print(output)

    if not report.is_successful:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
