"""Generate a JSON dump of fights from the public Google Sheet workbook.

The script downloads the ``PlayerList`` worksheet to obtain the canonical
spellings of player names and then walks through every other worksheet,
parses the fight tables and normalises participant names. The output JSON is
written either to stdout or to a file specified via ``--output``.

The parsing logic reuses the ``_SheetParser`` from ``app.tour_statistics_importer``
so that the behaviour matches the importer used by the application.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tour_statistics_importer import (  # noqa: E402  - imported after sys.path tweak
    _SheetParser,
    _column_letter,
    _normalise_text,
)

USER_AGENT = "Mozilla/5.0 (compatible; PanenkaFightJsonGenerator/1.0)"
HTMLVIEW_ENDPOINT = "https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview"
GVIZ_CSV_ENDPOINT = (
    "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
)
PLAYER_LIST_SHEET = "PlayerList"

# Regex used in ``scripts/season2/download_sheet_csvs.py`` – reused here to keep
# the parsing logic consistent across utilities.
SHEET_PATTERN = re.compile(
    r"items.push\(\{name: \"([^\"]+)\",.*?gid: \"(\d+)\"", re.DOTALL
)


class FetchError(RuntimeError):
    """Raised when Google Sheets data cannot be retrieved."""


@dataclass(frozen=True)
class SheetInfo:
    """Basic metadata about a worksheet inside the spreadsheet."""

    name: str
    gid: str


def _http_get(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if response.status_code == 404:
        raise FetchError(f"Google Sheets resource not found: {url}")
    response.raise_for_status()
    return response.text


def fetch_sheet_catalog(sheet_id: str) -> List[SheetInfo]:
    """Return the list of worksheets with their GIDs."""

    html = _http_get(HTMLVIEW_ENDPOINT.format(sheet_id=sheet_id))
    entries = [SheetInfo(name=name, gid=gid) for name, gid in SHEET_PATTERN.findall(html)]
    if not entries:
        raise FetchError(
            "Unable to locate sheet metadata. Make sure the spreadsheet is shared "
            "publicly and the ID is correct."
        )
    return entries


def fetch_sheet_rows(sheet_id: str, gid: str) -> List[List[str]]:
    """Download a worksheet and return it as a matrix of strings."""

    csv_text = _http_get(GVIZ_CSV_ENDPOINT.format(sheet_id=sheet_id, gid=gid))
    reader = csv.reader(csv_text.splitlines())
    return [list(row) for row in reader]


def build_player_map(rows: Iterable[Iterable[str]]) -> dict[str, str]:
    """Create a mapping from normalised aliases to canonical player names."""

    alias_map: dict[str, str] = {}
    for raw_row in rows:
        row = list(raw_row)
        if not row:
            continue
        canonical = row[0].strip()
        if not canonical:
            continue
        canonical_normalised = _normalise_text(canonical)
        alias_map[canonical_normalised] = canonical
        for alias in row[1:]:
            alias = alias.strip()
            if not alias:
                continue
            alias_map[_normalise_text(alias)] = canonical
    if not alias_map:
        raise ValueError("PlayerList worksheet does not contain any player names.")
    return alias_map


def normalise_name(name: str, aliases: dict[str, str]) -> str:
    """Resolve ``name`` to its canonical spelling using the alias map."""

    normalised = _normalise_text(name)
    if normalised in aliases:
        return aliases[normalised]
    raise KeyError(f"Не удалось найти игрока '{name}' в PlayerList")


def _format_sheet_range(start: int, end: int) -> str:
    start_letter = _column_letter(start)
    end_letter = _column_letter(max(start, end - 1))
    return f"{start_letter}:{end_letter}"


def generate_dataset(sheet_id: str, *, include_sheet_details: bool = True) -> dict:
    """Download the spreadsheet and build a JSON-serialisable dataset."""

    sheets = fetch_sheet_catalog(sheet_id)
    player_sheet = next((sheet for sheet in sheets if sheet.name == PLAYER_LIST_SHEET), None)
    if player_sheet is None:
        raise FetchError("Worksheet 'PlayerList' was not found in the spreadsheet.")

    player_rows = fetch_sheet_rows(sheet_id, player_sheet.gid)
    alias_map = build_player_map(player_rows)

    fights: List[dict] = []
    unknown_names: set[str] = set()

    for sheet in sheets:
        if sheet.name == PLAYER_LIST_SHEET:
            continue
        rows = fetch_sheet_rows(sheet_id, sheet.gid)
        parser = _SheetParser(rows)
        for fight in parser.parse():
            participants = []
            for seat, (name, total) in enumerate(
                zip(fight.player_names, fight.player_totals), start=1
            ):
                try:
                    corrected = normalise_name(name, alias_map)
                except KeyError:
                    corrected = name.strip()
                    unknown_names.add(name.strip())
                participants.append(
                    {
                        "seat": seat,
                        "original_name": name.strip(),
                        "name": corrected,
                        "total_score": total,
                    }
                )

            questions = []
            for order, question in enumerate(fight.questions, start=1):
                questions.append(
                    {
                        "order": order,
                        "theme": question.theme.strip() if question.theme else "",
                        "nominal": question.nominal,
                        "deltas": question.deltas,
                    }
                )

            fight_entry = {
                "fight_code": fight.fight_code,
                "season_number": fight.season_number,
                "tour_number": fight.tour_number,
                "fight_number": fight.fight_number,
                "participants": participants,
                "questions": questions,
            }
            if include_sheet_details:
                fight_entry["sheet"] = {
                    "name": sheet.name,
                    "gid": sheet.gid,
                    "column_range": _format_sheet_range(fight.start_column, fight.end_column),
                    "question_row_start": min(q.row_index for q in fight.questions) + 1,
                    "question_row_end": max(q.row_index for q in fight.questions) + 1,
                }
            fights.append(fight_entry)

    dataset = {
        "spreadsheet_id": sheet_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fights": fights,
    }
    if unknown_names:
        dataset["unknown_names"] = sorted(unknown_names)
    return dataset


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet-id", required=True, help="Google Sheets document identifier.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path where the JSON dataset should be written. Defaults to stdout.",
    )
    parser.add_argument(
        "--no-sheet-details",
        action="store_true",
        help="Do not include sheet metadata (column ranges and row numbers) in the output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dataset = generate_dataset(args.sheet_id, include_sheet_details=not args.no_sheet_details)
    except (FetchError, ValueError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        json.dump(dataset, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    if dataset.get("unknown_names"):
        print(
            "Warning: Some names could not be matched to PlayerList and were left as-is.",
            file=sys.stderr,
        )
        for name in dataset["unknown_names"]:
            print(f"  - {name}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
