"""Import Season 1 tour statistics into :mod:`TourStatisticsStore`."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional, Sequence

from .tour_statistics_store import TourStatisticsStore

_FIGHT_CODE_RE = re.compile(
    r"S(?P<season>\d{2})E(?P<tour>\d{2})F(?P<fight>\d{2})",
    flags=re.IGNORECASE,
)
_NOMINAL_VALUES = {"10", "20", "30", "40", "50"}


def _normalise_text(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value.strip().lower())
    return value.replace("ё", "е")


def _parse_int(value: str) -> int:
    cleaned = value.replace("\u2212", "-").replace("−", "-").strip()
    if not cleaned:
        return 0
    cleaned = cleaned.lstrip("+")
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return int(float(cleaned.replace(",", ".")))


def _looks_like_theme(value: str) -> bool:
    if not value:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    # Ignore numeric tokens and +/- deltas.
    try:
        _parse_int(stripped)
    except ValueError:
        pass
    else:
        return False
    return any(ch.isalpha() for ch in stripped)


def _column_letter(index: int) -> str:
    if index < 0:
        raise ValueError("Column index must be non-negative")
    result = ""
    while True:
        index, remainder = divmod(index, 26)
        result = chr(ord("A") + remainder) + result
        if index == 0:
            break
        index -= 1
    return result


@dataclass
class SheetQuestion:
    nominal: int
    theme: str
    deltas: List[int]
    row_index: int


@dataclass
class SheetFight:
    fight_code: str
    season_number: int
    tour_number: int
    fight_number: int
    start_column: int
    end_column: int
    player_names: List[str]
    player_totals: List[int]
    questions: List[SheetQuestion]


class _SheetParser:
    def __init__(self, rows: Sequence[Sequence[str]]):
        self._rows: List[List[str]] = [list(row) for row in rows]

    def parse(self) -> List[SheetFight]:
        if not self._rows:
            return []
        header = self._rows[0]
        start_columns = [
            idx
            for idx, cell in enumerate(header)
            if _FIGHT_CODE_RE.fullmatch(cell.strip())
        ]
        fights: List[SheetFight] = []
        for pos, start in enumerate(start_columns):
            fight_code = header[start].strip()
            end = self._detect_block_end(start, start_columns[pos + 1] if pos + 1 < len(start_columns) else len(header))
            player_names, player_totals = self._extract_players(start, end)
            if not player_names:
                continue
            nominal_column = self._detect_nominal_column(start, end)
            questions = self._extract_questions(start, nominal_column, player_names)
            if not questions:
                continue
            match = _FIGHT_CODE_RE.fullmatch(fight_code)
            if not match:
                continue
            fights.append(
                SheetFight(
                    fight_code=fight_code,
                    season_number=int(match.group("season")),
                    tour_number=int(match.group("tour")),
                    fight_number=int(match.group("fight")),
                    start_column=start,
                    end_column=end,
                    player_names=player_names,
                    player_totals=player_totals,
                    questions=questions,
                )
            )
        return fights

    def _detect_block_end(self, start: int, next_start: int) -> int:
        end = next_start
        for column in range(start + 1, next_start):
            if self._is_blank_column(column):
                end = column
                break
        return end

    def _is_blank_column(self, column: int) -> bool:
        for row in self._rows:
            if column < len(row) and row[column].strip():
                return False
        return True

    def _extract_players(self, start: int, end: int) -> tuple[List[str], List[int]]:
        player_row = self._rows[1] if len(self._rows) > 1 else []
        total_row = self._rows[2] if len(self._rows) > 2 else []
        player_names: List[str] = []
        totals: List[int] = []
        for column in range(start + 1, end):
            name = player_row[column].strip() if column < len(player_row) else ""
            if not name:
                continue
            lowered = name.lower()
            if lowered in {"номинал", "темы"}:
                continue
            player_names.append(name)
            total_raw = total_row[column] if column < len(total_row) else ""
            totals.append(_parse_int(total_raw or ""))
        return player_names, totals

    def _detect_nominal_column(self, start: int, end: int) -> int:
        header = self._rows[1] if len(self._rows) > 1 else []
        for column in range(start, end):
            header_value = header[column].strip().lower() if column < len(header) else ""
            if header_value == "номинал":
                return column
        best_column = end - 1
        best_hits = -1
        for column in range(start, end):
            hits = 0
            for row in self._rows[3:]:
                if column < len(row) and row[column].strip() in _NOMINAL_VALUES:
                    hits += 1
            if hits > best_hits:
                best_hits = hits
                best_column = column
        return best_column

    def _extract_questions(self, start: int, nominal_col: int, player_names: Sequence[str]) -> List[SheetQuestion]:
        questions: List[SheetQuestion] = []
        player_columns = [start + 1 + idx for idx in range(len(player_names))]
        current_theme: Optional[str] = None
        for row_index in range(3, len(self._rows)):
            row = self._rows[row_index]
            nominal_raw = row[nominal_col].strip() if nominal_col < len(row) else ""
            if nominal_raw in _NOMINAL_VALUES:
                nominal = int(nominal_raw)
                theme = self._resolve_theme(row, start, nominal_col) or current_theme
                if theme is None:
                    continue
                current_theme = theme
                deltas: List[int] = []
                for column in player_columns:
                    cell = row[column] if column < len(row) else ""
                    deltas.append(_parse_int(cell or ""))
                questions.append(
                    SheetQuestion(nominal=nominal, theme=current_theme, deltas=deltas, row_index=row_index)
                )
            else:
                theme_candidate = self._resolve_theme(row, start, nominal_col)
                if theme_candidate:
                    current_theme = theme_candidate
        return questions

    def _resolve_theme(self, row: Sequence[str], start: int, nominal_col: int) -> Optional[str]:
        for column in range(start, nominal_col):
            if column >= len(row):
                break
            value = row[column]
            if _looks_like_theme(value):
                return value.strip()
        return None


@dataclass
class TourStatisticsImportSummary:
    fights_imported: int = 0
    participants_inserted: int = 0
    questions_inserted: int = 0
    question_results_inserted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "fights_imported": self.fights_imported,
            "participants_inserted": self.participants_inserted,
            "questions_inserted": self.questions_inserted,
            "question_results_inserted": self.question_results_inserted,
        }


class TourStatisticsImporter:
    """Load Season 1 Google Sheet exports into :class:`TourStatisticsStore`."""

    def __init__(self, *, store: TourStatisticsStore, sheet_id: str, sheet_name: str) -> None:
        self._store = store
        self._sheet_id = sheet_id
        self._sheet_name = sheet_name

    def import_rows(self, rows: Sequence[Sequence[str]]) -> TourStatisticsImportSummary:
        parser = _SheetParser(rows)
        fights = parser.parse()
        summary = TourStatisticsImportSummary()
        if not fights:
            return summary

        self._store.ensure_schema()
        with self._store.connection() as conn:
            import_id = self._create_import_record(conn)
            conn.commit()
            try:
                conn.execute("BEGIN")
                for fight in fights:
                    self._delete_existing_fight(conn, fight.fight_code)
                    season_id = self._ensure_season(conn, fight.season_number)
                    tour_id = self._ensure_tour(conn, season_id, fight.tour_number)
                    fight_id = self._insert_fight(conn, tour_id, import_id, fight)
                    participant_ids = self._insert_participants(conn, fight_id, fight)
                    question_stats = self._insert_questions(conn, fight_id, participant_ids, fight)
                    summary.fights_imported += 1
                    summary.participants_inserted += len(participant_ids)
                    summary.questions_inserted += question_stats["questions"]
                    summary.question_results_inserted += question_stats["question_results"]
                self._complete_import(conn, import_id, status="success")
                conn.commit()
            except Exception as exc:  # pragma: no cover - defensive path
                conn.rollback()
                self._complete_import(conn, import_id, status="failed", message=str(exc))
                conn.commit()
                raise
        return summary

    def _create_import_record(self, conn) -> int:
        cursor = conn.execute(
            (
                "INSERT INTO imports (source, source_identifier, sheet_name, started_at, status) "
                "VALUES (?, ?, ?, datetime('now'), 'pending')"
            ),
            ("google_sheets", self._sheet_id, self._sheet_name),
        )
        return int(cursor.lastrowid)

    def _complete_import(self, conn, import_id: int, *, status: str, message: Optional[str] = None) -> None:
        conn.execute(
            "UPDATE imports SET finished_at = datetime('now'), status = ?, message = COALESCE(?, message) WHERE id = ?",
            (status, message, import_id),
        )

    def _ensure_season(self, conn, season_number: int) -> int:
        row = conn.execute(
            "SELECT id FROM seasons WHERE season_number = ?",
            (season_number,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        code = f"S{season_number:02d}"
        cursor = conn.execute(
            "INSERT INTO seasons (season_number, code) VALUES (?, ?)",
            (season_number, code),
        )
        return int(cursor.lastrowid)

    def _ensure_tour(self, conn, season_id: int, tour_number: int) -> int:
        row = conn.execute(
            "SELECT id FROM tours WHERE season_id = ? AND tour_number = ?",
            (season_id, tour_number),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        code = f"S{self._season_number_from_id(conn, season_id):02d}E{tour_number:02d}"
        cursor = conn.execute(
            "INSERT INTO tours (season_id, tour_number, code) VALUES (?, ?, ?)",
            (season_id, tour_number, code),
        )
        return int(cursor.lastrowid)

    def _season_number_from_id(self, conn, season_id: int) -> int:
        row = conn.execute("SELECT season_number FROM seasons WHERE id = ?", (season_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown season id {season_id}")
        return int(row["season_number"])

    def _delete_existing_fight(self, conn, fight_code: str) -> None:
        conn.execute("DELETE FROM fights WHERE fight_code = ?", (fight_code,))

    def _insert_fight(self, conn, tour_id: int, import_id: int, fight: SheetFight) -> int:
        row_start = min(question.row_index for question in fight.questions) + 1
        row_end = max(question.row_index for question in fight.questions) + 1
        start_letter = _column_letter(fight.start_column)
        end_letter = _column_letter(fight.end_column - 1)
        sheet_range = f"{start_letter}:{end_letter}"
        cursor = conn.execute(
            (
                "INSERT INTO fights (tour_id, fight_number, fight_code, sheet_column_range, "
                "question_row_start, question_row_end, import_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                tour_id,
                fight.fight_number,
                fight.fight_code,
                sheet_range,
                row_start,
                row_end,
                import_id,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_participants(self, conn, fight_id: int, fight: SheetFight) -> List[int]:
        participant_ids: List[int] = []
        for index, (name, total) in enumerate(zip(fight.player_names, fight.player_totals), start=1):
            player_id = self._lookup_player_id(conn, name)
            cursor = conn.execute(
                (
                    "INSERT INTO fight_participants (fight_id, player_id, seat_index, total_score) "
                    "VALUES (?, ?, ?, ?)"
                ),
                (fight_id, player_id, index, total),
            )
            participant_ids.append(int(cursor.lastrowid))
        calculated_totals = [0 for _ in fight.player_totals]
        for question in fight.questions:
            for idx, delta in enumerate(question.deltas):
                calculated_totals[idx] += delta
        if calculated_totals != fight.player_totals:
            raise ValueError("Participant totals do not match question deltas")
        return participant_ids

    def _lookup_player_id(self, conn, name: str) -> int:
        normalized = _normalise_text(name)
        row = conn.execute(
            "SELECT player_id FROM player_aliases WHERE normalized_alias = ?",
            (normalized,),
        ).fetchone()
        if row is not None:
            return int(row["player_id"])
        row = conn.execute(
            "SELECT id FROM players WHERE normalized_name = ?",
            (normalized,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        raise ValueError(f"Player alias not found for {name!r}")

    def _insert_questions(self, conn, fight_id: int, participant_ids: Sequence[int], fight: SheetFight) -> dict[str, int]:
        stats = {"questions": 0, "question_results": 0}
        question_records: list[tuple[int, SheetQuestion]] = []
        for order, question in enumerate(fight.questions, start=1):
            theme_id = self._ensure_theme(conn, question.theme)
            cursor = conn.execute(
                (
                    "INSERT INTO questions (fight_id, theme_id, question_order, nominal, sheet_row) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (
                    fight_id,
                    theme_id,
                    order,
                    question.nominal,
                    question.row_index + 1,
                ),
            )
            question_id = int(cursor.lastrowid)
            stats["questions"] += 1
            question_records.append((question_id, question))

        for question_id, question in question_records:
            for participant_id, delta in zip(participant_ids, question.deltas):
                conn.execute(
                    (
                        "INSERT INTO question_results (question_id, participant_id, delta, is_correct) "
                        "VALUES (?, ?, ?, ?)"
                    ),
                    (
                        question_id,
                        participant_id,
                        delta,
                        1 if delta > 0 else 0,
                    ),
                )
                stats["question_results"] += 1
        return stats

    def _ensure_theme(self, conn, title: str) -> int:
        normalized = title.strip()
        row = conn.execute(
            "SELECT id FROM themes WHERE title = ?",
            (normalized,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        cursor = conn.execute(
            "INSERT INTO themes (title) VALUES (?)",
            (normalized,),
        )
        return int(cursor.lastrowid)


__all__ = [
    "TourStatisticsImporter",
    "TourStatisticsImportSummary",
]
