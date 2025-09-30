"""Utilities for extracting Season 2 fight rosters from supporting spreadsheets."""

from __future__ import annotations

import csv
import re
from pathlib import Path

_FIGHT_CODE_RE = re.compile(r"s?(?P<season>\d{2})e(?P<tour>\d{2})", re.IGNORECASE)
_PLAYER_LINE_RE = re.compile(r"(?P<name>.+?)\s+[+\-\u2212]?\d")


def _normalise_name(value: str) -> str:
    value = value.strip()
    value = value.replace("\u2212", "-").replace("−", "-")
    value = re.sub(r"\s+", " ", value)
    return value


def _extract_player_names(block: str) -> list[str]:
    names: list[str] = []
    for line in block.splitlines():
        candidate = _normalise_name(line)
        if not candidate:
            continue
        match = _PLAYER_LINE_RE.match(candidate)
        if not match:
            continue
        name = _normalise_name(match.group("name"))
        if name and name.lower() not in {"host", "miss"}:
            names.append(name)
    return names


def parse_clashes_rosters(csv_path: Path) -> dict[tuple[int, int], list[str]]:
    """Parse the `Clashes` Season 2 sheet into tour/fight rosters.

    The sheet organises tours by row (labelled ``S02E{tour}``) and individual
    fights by column. Each cell lists the participating players in finishing
    order alongside aggregate scoring metadata, e.g. ``"Имя 320 (440/-120, 15/4)"``.
    Only the player names are required when enriching fight participants.
    """

    if not csv_path.exists():
        return {}

    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    if not rows:
        return {}

    header = rows[0]
    fight_columns: list[tuple[int, int]] = []
    for index, cell in enumerate(header[1:], start=1):
        label = cell.strip()
        if label.isdigit():
            fight_columns.append((index, int(label)))

    if not fight_columns:
        return {}

    rosters: dict[tuple[int, int], list[str]] = {}

    for row in rows[1:]:
        if not row:
            continue
        raw_code = (row[0] or "").strip()
        if not raw_code:
            continue
        match = _FIGHT_CODE_RE.fullmatch(raw_code.lower())
        if not match:
            continue
        tour_number = int(match.group("tour"))

        for column_index, fight_number in fight_columns:
            if column_index >= len(row):
                continue
            cell_value = (row[column_index] or "").strip()
            if not cell_value:
                continue
            participants = _extract_player_names(cell_value)
            if participants:
                rosters[(tour_number, fight_number)] = participants

    return rosters


__all__ = ["parse_clashes_rosters"]
