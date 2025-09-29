"""Import buzzer fight results from Google Sheets.

This module implements the strategy described in ``docs/tour_statistics_import.md``
for importing fight results. It downloads public Google Sheets HTML snapshots,
parses the waffle tables and normalises the data into a structured JSON-friendly
format. A small CLI helper mirrors ``question_importer.py`` and allows
regenerating a fixture with the parsed data.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import requests
from html.parser import HTMLParser


SPREADSHEET_ID = "1ehQabU98lFzeInoJwvEIGpyZeuv2NFkPdnhoXYzDmT0"

# Mapping of tour numbers to sheet GIDs in the spreadsheet above. The user
# request targets season 01 tours 02-11, hence we include the corresponding
# sheets here.
TOUR_GIDS: Dict[int, int] = {
    2: 0,
    3: 1726247583,
    4: 159521265,
    5: 483540880,
    6: 817121038,
    7: 1098565637,
    8: 809001734,
    9: 839687562,
    10: 157788003,
    11: 1392511719,
}

USER_AGENT = "Mozilla/5.0 (compatible; PanenkaResultsImporter/1.0)"


class _WaffleParser(HTMLParser):
    """Parse a Google Sheets "waffle" table into a list of rows."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._current_table: Optional[List[List[str]]] = None
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[str] = None
        self._current_colspan: int = 1

    def handle_starttag(self, tag: str, attrs: Sequence[tuple[str, Optional[str]]]):
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("class") == "waffle":
            self._current_table = []
            self.tables.append(self._current_table)
        elif self._current_table is not None:
            if tag == "tr":
                self._current_row = []
                self._current_table.append(self._current_row)
            elif tag in {"td", "th"}:
                self._current_cell = ""
                try:
                    self._current_colspan = int(attrs_dict.get("colspan", "1"))
                except (TypeError, ValueError):
                    self._current_colspan = 1
            elif tag == "br" and self._current_cell is not None:
                self._current_cell += "\n"

    def handle_endtag(self, tag: str):
        if tag == "table":
            self._current_table = None
        elif self._current_table is not None:
            if tag == "tr":
                self._current_row = None
            elif tag in {"td", "th"} and self._current_row is not None:
                value = (self._current_cell or "").strip()
                for index in range(self._current_colspan):
                    self._current_row.append(value if index == 0 else "")
                self._current_cell = None
                self._current_colspan = 1

    def handle_data(self, data: str):
        if self._current_cell is not None:
            self._current_cell += data


def _fetch_waffle_table(gid: int) -> List[List[str]]:
    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{SPREADSHEET_ID}/htmlview/sheet?headers=false&gid={gid}"
    )
    response = requests.get(url, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    parser = _WaffleParser()
    parser.feed(response.text)
    if not parser.tables:
        raise ValueError(f"No waffle table found for gid={gid}")
    return parser.tables[0]


def _coerce_int(value: str) -> int:
    value = value.strip().replace("\u2212", "-").replace("−", "-").replace("\xa0", "")
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return int(float(value))


THEME_GUARD_PREFIXES = (
    "после",
    "нажатия",
    "сумма",
    "плюсы",
    "минусы",
    "всего",
    "count",
)


def _is_theme_cell(text: str) -> bool:
    if not text:
        return False
    text = text.strip()
    if not text:
        return False
    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in THEME_GUARD_PREFIXES):
        return False
    return True


@dataclass
class QuestionResult:
    order: int
    theme: str
    nominal: int
    deltas: List[int]

    def as_dict(self) -> dict:
        return {
            "order": self.order,
            "theme": self.theme,
            "nominal": self.nominal,
            "results": [
                {"delta": delta, "is_correct": bool(delta > 0)} for delta in self.deltas
            ],
        }


@dataclass
class FightResults:
    code: str
    letter: str
    players: List[dict]
    questions: List[QuestionResult]

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "letter": self.letter,
            "players": self.players,
            "questions": [question.as_dict() for question in self.questions],
        }


def _detect_fight_columns(table: List[List[str]]) -> List[int]:
    header_row = table[1]
    fight_columns = [idx for idx, value in enumerate(header_row) if value.startswith("Бой")]
    if fight_columns:
        return fight_columns

    player_row = table[2]
    detected: List[int] = []
    idx = 0
    while idx < len(player_row):
        cell = player_row[idx].strip()
        if not cell:
            idx += 1
            continue
        block_values: List[str] = []
        j = idx
        while j < len(player_row) and player_row[j].strip():
            block_values.append(player_row[j].strip())
            j += 1
        if len(block_values) >= 2 and any(any(ch.isalpha() for ch in value) for value in block_values):
            detected.append(idx)
        idx = j
    return detected


def _parse_tour(season_number: int, tour_number: int, gid: int) -> dict:
    table = _fetch_waffle_table(gid)
    if len(table) < 4:
        raise ValueError(f"Unexpected table height for tour {tour_number}")

    header_row = table[1]
    fight_columns = _detect_fight_columns(table)
    if not fight_columns:
        raise ValueError(f"No fights found in tour {tour_number}")

    fights: List[FightResults] = []
    for fight_index, start_col in enumerate(fight_columns, start=1):
        header_value = header_row[start_col].strip() if start_col < len(header_row) else ""
        if header_value:
            letter = header_value.split()[-1]
        else:
            # Some sheets omit the "Бой <letter>" labels. Fall back to a
            # sequential Latin alphabet marker to retain a stable identifier.
            letter = chr(ord("A") + fight_index - 1)
        players = [table[2][start_col + offset] for offset in range(4)]
        totals = [
            _coerce_int(table[3][start_col + offset])
            for offset in range(4)
        ]
        player_payload = [
            {"name": name, "total": total}
            for name, total in zip(players, totals)
        ]

        current_theme: Optional[str] = None
        questions: List[QuestionResult] = []
        order = 0
        for row in table[4:]:
            if len(row) <= start_col + 5:
                continue
            nominal_cell = row[start_col + 5].strip()
            if nominal_cell in {"10", "20", "30", "40", "50"}:
                if current_theme is None:
                    raise ValueError(
                        f"Encountered question row without theme in tour {tour_number}"
                    )
                order += 1
                deltas = [
                    _coerce_int(row[start_col + offset])
                    for offset in range(4)
                ]
                questions.append(
                    QuestionResult(
                        order=order,
                        theme=current_theme,
                        nominal=int(nominal_cell),
                        deltas=deltas,
                    )
                )
                continue

            theme_cell = row[3] if len(row) > 3 else ""
            if _is_theme_cell(theme_cell):
                current_theme = theme_cell.strip()

        code = f"S{season_number:02d}E{tour_number:02d}F{fight_index:02d}"
        fights.append(
            FightResults(
                code=code,
                letter=letter,
                players=player_payload,
                questions=questions,
            )
        )

    return {
        "tour_number": tour_number,
        "gid": gid,
        "fights": [fight.as_dict() for fight in fights],
    }


def import_season_results(
    season_number: int,
    *,
    tour_numbers: Optional[Iterable[int]] = None,
    dump_fixture_path: Optional[Path] = None,
) -> dict:
    """Import fight results for the requested tours of a season.

    Args:
        season_number: Season number, e.g. ``1`` for season 01.
        tour_numbers: Optional iterable limiting the processed tours. If omitted
            all known tours from ``TOUR_GIDS`` are imported.
        dump_fixture_path: Optional path to store the results as JSON.

    Returns:
        A dictionary describing the imported season used for fixture dumping and
        for potential downstream processing.
    """

    if tour_numbers is None:
        selected_tours = sorted(TOUR_GIDS)
    else:
        selected_tours = sorted(int(tour) for tour in tour_numbers)

    missing_tours = [tour for tour in selected_tours if tour not in TOUR_GIDS]
    if missing_tours:
        raise ValueError(f"No GID mapping available for tours: {missing_tours}")

    tours_payload = [
        _parse_tour(season_number, tour_number, TOUR_GIDS[tour_number])
        for tour_number in selected_tours
    ]

    season_payload = {
        "season_number": season_number,
        "tours": tours_payload,
    }

    if dump_fixture_path is not None:
        dump_fixture_path.parent.mkdir(parents=True, exist_ok=True)
        dump_fixture_path.write_text(
            json.dumps(season_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return season_payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import buzzer fight results from Google Sheets."
    )
    parser.add_argument(
        "--season",
        type=int,
        default=1,
        help="Season number to import (default: 1).",
    )
    parser.add_argument(
        "--tours",
        type=int,
        nargs="*",
        help="Optional list of tour numbers to import (defaults to all known tours).",
    )
    parser.add_argument(
        "--dump-fixture",
        type=Path,
        help="Optional path to write the imported data as JSON.",
    )
    args = parser.parse_args(argv)

    import_season_results(
        args.season,
        tour_numbers=args.tours,
        dump_fixture_path=args.dump_fixture,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI helper
    raise SystemExit(main())
