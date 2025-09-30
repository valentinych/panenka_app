"""Import Season 2 tour results into the local staging database."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.season2 import Season2Importer, Season2ResultsStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/raw/season02/csv"),
        help="Directory containing tour CSV snapshots.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/raw/season02/manifest.json"),
        help="Manifest describing Season 2 worksheets and CSV filenames.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        help="Optional override for the results database path.",
    )
    parser.add_argument(
        "--tours",
        type=int,
        nargs="*",
        help="Optional list of tour numbers to import (defaults to all tours present in the manifest).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    store = Season2ResultsStore(db_path=str(args.db_path) if args.db_path else None)
    importer = Season2Importer(store=store, data_root=args.data_root, manifest_path=args.manifest)

    summary = importer.import_season(tours=args.tours)
    result = summary.as_dict()

    print("Imported Season 2 results:")
    for key, value in sorted(result.items()):
        print(f"  {key.replace('_', ' ')}: {value}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    raise SystemExit(main())

