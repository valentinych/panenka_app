"""Parsing helpers for Season 2 tour CSV snapshots.

The Season 2 Google Sheets export stores each tour as a matrix where fights
occupy column groups instead of rows. The first row of a tour contains ordinal
markers (currently all ``"1"``) for every fight block, followed by two columns
labelled ``"Ведущие тура"`` and ``"не играли"`` with host/inactive rosters.

Within a fight block the layout is consistent across tours:

* column 0 of the block is used for metadata and question nominal markers
  (``10`` … ``50``) in the order they are played;
* columns 1-4 contain per-player data (totals in the second row of the sheet and
  per-question deltas in the question rows);
* a trailing column can appear for host/inactive markers and is left blank in
  the totals row.

Season 2 introduces a few quirks compared to the Season 1 HTML exports:

* fight codes are absent – consumers must synthesise them from the tour number
  and the fight ordinal;
* player columns do not include explicit names; the Season 2 aggregate sheets
  must be consulted to map the roster later in the pipeline;
* zero deltas are stored as empty strings instead of explicit ``0`` values.

This module focuses on the structural parsing aspect so the importer can reason
about fights and question deltas again. Player identification is deferred to a
higher layer which can join with aggregate tables.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence
import csv

NOMINAL_VALUES = ("10", "20", "30", "40", "50")
GUARD_HEADERS = {"Ведущие тура", "не играли"}


def _read_csv(path: Path) -> List[List[str]]:
    with path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        return [list(row) for row in reader]


def _normalise_int(value: str) -> int:
    """Coerce Season 2 numeric cells into integers.

    The sheets use blanks for zero and occasionally include non-breaking spaces
    or a Unicode minus. Everything that cannot be parsed is treated as zero so
    downstream validation can flag unexpected tokens.
    """

    if not value:
        return 0
    cleaned = value.replace("\u2212", "-").replace("−", "-").replace("\xa0", "").strip()
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        try:
            return int(float(cleaned.replace(",", ".")))
        except ValueError:
            return 0


@dataclass
class Season2QuestionRow:
    """Question row captured from a Season 2 tour sheet."""

    nominal: int
    deltas: List[int]
    source_row: int


@dataclass
class Season2Fight:
    """Parsed fight payload extracted from a tour sheet."""

    ordinal: int
    start_column: int
    player_columns: List[int]
    player_totals: List[int]
    questions: List[Season2QuestionRow]

    @property
    def question_count(self) -> int:
        return len(self.questions)


class Season2TourSheet:
    """Utility for iterating fights within a Season 2 tour CSV export."""

    def __init__(self, *, tour_number: int, rows: Sequence[Sequence[str]]):
        self.tour_number = tour_number
        # Normalise rows to lists to allow index lookups without surprises.
        self._rows: List[List[str]] = [list(row) for row in rows]
        if not self._rows:
            raise ValueError("Tour sheet has no rows")

    @classmethod
    def from_csv(cls, csv_path: Path, *, tour_number: int) -> "Season2TourSheet":
        rows = _read_csv(csv_path)
        return cls(tour_number=tour_number, rows=rows)

    def iter_fights(self) -> Iterator[Season2Fight]:
        header = self._rows[0]
        # Fights occupy column groups until the "hosts/inactive" roster begins.
        try:
            cutoff = min(header.index(marker) for marker in GUARD_HEADERS if marker in header)
        except ValueError:
            cutoff = len(header)

        start_columns: List[int] = [
            idx
            for idx, value in enumerate(header[:cutoff])
            if value.strip()
        ]
        for ordinal, start_col in enumerate(start_columns, start=1):
            end_col = self._next_start(start_columns, start_col, cutoff)
            player_cols = self._detect_player_columns(start_col, end_col)
            totals = [self._cell_value(2, col) for col in player_cols]
            questions = list(self._collect_questions(start_col, player_cols))
            if not questions:
                continue
            yield Season2Fight(
                ordinal=ordinal,
                start_column=start_col,
                player_columns=player_cols,
                player_totals=totals,
                questions=questions,
            )

    # Internal helpers -------------------------------------------------

    def _next_start(self, start_columns: Sequence[int], current: int, cutoff: int) -> int:
        for candidate in start_columns:
            if candidate > current:
                return candidate
        return cutoff

    def _cell_value(self, row_index: int, column: int) -> int:
        try:
            value = self._rows[row_index][column]
        except IndexError:
            return 0
        return _normalise_int(value)

    def _detect_player_columns(self, start_col: int, end_col: int) -> List[int]:
        columns: List[int] = []
        for column in range(start_col + 1, end_col):
            total_raw = self._safe_cell(2, column)
            if not total_raw.strip():
                # Skip columns that never record totals (hosts/inactive roster).
                continue
            columns.append(column)
        return columns

    def _collect_questions(
        self, start_col: int, player_cols: Sequence[int]
    ) -> Iterable[Season2QuestionRow]:
        question_rows: List[Season2QuestionRow] = []
        for row_index, row in enumerate(self._rows):
            try:
                cell_value = row[start_col]
            except IndexError:
                continue
            if cell_value not in NOMINAL_VALUES:
                continue
            nominal = int(cell_value)
            deltas = [self._cell_value(row_index, column) for column in player_cols]
            question_rows.append(Season2QuestionRow(nominal=nominal, deltas=deltas, source_row=row_index))
            if len(question_rows) == len(NOMINAL_VALUES):
                break
        return question_rows

    def _safe_cell(self, row_index: int, column: int) -> str:
        try:
            return self._rows[row_index][column]
        except IndexError:
            return ""
