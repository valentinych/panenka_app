"""Import fight statistics from a Google Sheet into the tour statistics DB."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence
from urllib.parse import urlencode

import requests

from app.tour_statistics_importer import TourStatisticsImporter
from app.tour_statistics_store import TourStatisticsStore

USER_AGENT = "Mozilla/5.0 (compatible; PanenkaTourStatsImporter/1.0)"


class ImportFailure(Exception):
    """Raised when Google Sheets data cannot be fetched or parsed."""


def _fetch_sheet_csv(sheet_id: str, sheet_name: str, sheet_range: str) -> List[List[str]]:
    """Download a rectangular range from Google Sheets as CSV."""

    params = urlencode({"format": "csv", "sheet": sheet_name, "range": sheet_range})
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{params}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if response.status_code == 404:
        raise ImportFailure(
            "Google Sheets document or range was not found. "
            "Check that the document is shared publicly and the range is correct."
        )
    response.raise_for_status()

    csv_file = io.StringIO(response.text)
    reader = csv.reader(csv_file)
    return [list(row) for row in reader]


@dataclass
class QualityCheckResult:
    description: str
    ok: bool
    details: Optional[str] = None

    def format(self) -> str:
        status = "OK" if self.ok else "FAIL"
        if self.details:
            return f"[{status}] {self.description}: {self.details}"
        return f"[{status}] {self.description}"


def _run_quality_checks(store: TourStatisticsStore, fight_codes: Sequence[str]) -> List[QualityCheckResult]:
    if not fight_codes:
        return []

    placeholders = ",".join("?" for _ in fight_codes)
    results: List[QualityCheckResult] = []

    with store.connection() as conn:
        fights_count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM fights WHERE fight_code IN ({placeholders})",
            tuple(fight_codes),
        ).fetchone()
        fights_count = int(fights_count_row["cnt"] if fights_count_row is not None else 0)
        results.append(
            QualityCheckResult(
                description="Fight count matches sheet headers",
                ok=fights_count == len(fight_codes),
                details=f"database={fights_count}, sheet={len(fight_codes)}",
            )
        )

        totals_query = f"""
            SELECT fp.id AS participant_id,
                   fp.total_score AS expected_total,
                   COALESCE(SUM(qr.delta), 0) AS aggregated_total
            FROM fight_participants fp
            LEFT JOIN question_results qr ON qr.participant_id = fp.id
            WHERE fp.fight_id IN (
                SELECT id FROM fights WHERE fight_code IN ({placeholders})
            )
            GROUP BY fp.id
        """
        mismatches = [
            row
            for row in conn.execute(totals_query, tuple(fight_codes))
            if int(row["expected_total"]) != int(row["aggregated_total"])
        ]
        results.append(
            QualityCheckResult(
                description="Participant totals agree with per-question deltas",
                ok=not mismatches,
                details="all participants match" if not mismatches else f"mismatches={len(mismatches)}",
            )
        )

        alias_query = f"""
            SELECT p.full_name AS name
            FROM fight_participants fp
            JOIN players p ON p.id = fp.player_id
            LEFT JOIN player_aliases pa ON pa.player_id = p.id
            WHERE fp.fight_id IN (
                SELECT id FROM fights WHERE fight_code IN ({placeholders})
            )
            GROUP BY p.id
            HAVING COUNT(pa.id) = 0
        """
        missing_aliases = [row["name"] for row in conn.execute(alias_query, tuple(fight_codes))]
        results.append(
            QualityCheckResult(
                description="All participants have aliases in PlayerList",
                ok=not missing_aliases,
                details="all aliases present" if not missing_aliases else ", ".join(missing_aliases),
            )
        )

    return results


def _print_summary(summary) -> None:
    stats = summary.as_dict()
    print("Imported fights summary:")
    for key, value in stats.items():
        print(f"  - {key}: {value}")


def _run_import(
    *,
    sheet_id: str,
    sheet_name: str,
    sheet_range: str,
    store: TourStatisticsStore,
    dry_run: bool,
    trace_sql: bool,
) -> int:
    rows = _fetch_sheet_csv(sheet_id, sheet_name, sheet_range)
    if not rows:
        raise ImportFailure("The requested range returned an empty table")

    importer = TourStatisticsImporter(store=store, sheet_id=sheet_id, sheet_name=sheet_name)
    summary = importer.import_rows(
        rows,
        dry_run=dry_run,
        trace_sql=print if trace_sql else None,
    )
    _print_summary(summary)

    if dry_run:
        print("Dry-run complete. No changes were committed to the database.")
        return 0

    checks = _run_quality_checks(store, summary.fight_codes)
    if checks:
        print("\nQuality checks:")
        for check in checks:
            print("  " + check.format())
    failures = [check for check in checks if not check.ok]
    if failures:
        raise ImportFailure("Quality checks failed. Inspect the log above for details.")
    return summary.fights_imported


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import fight statistics from Google Sheets.")
    parser.add_argument("--sheet-id", required=True, help="Google Sheets document identifier.")
    parser.add_argument("--sheet-name", required=True, help="Worksheet name inside the spreadsheet.")
    parser.add_argument(
        "--range",
        required=True,
        dest="sheet_range",
        help="A1-notation range that contains the fight statistics (e.g. S01E02!A1:ZZ200).",
    )
    parser.add_argument(
        "--db-path",
        help="Optional path to the SQLite database. Defaults to PANENKA_TOUR_STATS_DB or the app directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the sheet and print SQL statements without committing changes.",
    )
    parser.add_argument(
        "--trace-sql",
        action="store_true",
        help="Print SQL statements as they are executed.",
    )

    args = parser.parse_args(argv)

    store = TourStatisticsStore(db_path=args.db_path)

    try:
        _run_import(
            sheet_id=args.sheet_id,
            sheet_name=args.sheet_name,
            sheet_range=args.sheet_range,
            store=store,
            dry_run=args.dry_run,
            trace_sql=args.trace_sql or args.dry_run,
        )
    except ImportFailure as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - execution guard
        print(f"Unexpected error during import: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

