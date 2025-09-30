"""Import Season 2 tour results into the staging database."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .results_store import Season2ResultsStore
from .tour_sheet_parser import Season2Fight, Season2TourSheet


@dataclass
class Season2ImportSummary:
    """Aggregate counters describing an import run."""

    tours_attempted: int = 0
    tours_imported: int = 0
    tours_skipped: int = 0
    fights_imported: int = 0
    fights_skipped: int = 0
    participants_inserted: int = 0
    questions_inserted: int = 0
    question_results_inserted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "tours_attempted": self.tours_attempted,
            "tours_imported": self.tours_imported,
            "tours_skipped": self.tours_skipped,
            "fights_imported": self.fights_imported,
            "fights_skipped": self.fights_skipped,
            "participants_inserted": self.participants_inserted,
            "questions_inserted": self.questions_inserted,
            "question_results_inserted": self.question_results_inserted,
        }


class Season2Importer:
    """Import Season 2 fight snapshots into the staging schema."""

    def __init__(
        self,
        *,
        store: Season2ResultsStore,
        data_root: Path,
        manifest_path: Path,
        season_number: int = 2,
        source: str = "season02_csv_snapshot",
    ) -> None:
        self._store = store
        self._data_root = Path(data_root)
        self._manifest_path = Path(manifest_path)
        self._season_number = season_number
        self._source = source

    # Public API -----------------------------------------------------

    def import_season(
        self,
        *,
        tours: Optional[Sequence[int]] = None,
    ) -> Season2ImportSummary:
        """Import the requested tours into the Season 2 results schema."""

        manifest = self._load_manifest()
        available_tours = sorted(manifest)
        if tours is None:
            selected_tours = available_tours
        else:
            selected_tours = sorted({int(tour) for tour in tours})

        summary = Season2ImportSummary()
        summary.tours_attempted = len(selected_tours)

        self._store.ensure_schema()
        with self._store.connection() as conn:
            season_id = self._ensure_season(conn)
            import_id = self._create_import_record(conn)
            conn.commit()
            try:
                conn.execute("BEGIN")
                for tour_number in selected_tours:
                    entry = manifest.get(tour_number)
                    if entry is None:
                        summary.tours_skipped += 1
                        continue

                    csv_path = self._data_root / entry["filename"]
                    if not csv_path.exists():
                        summary.tours_skipped += 1
                        continue

                    sheet = Season2TourSheet.from_csv(csv_path, tour_number=tour_number)
                    tour_id = self._ensure_tour(conn, season_id, tour_number, entry.get("gid"))
                    imported_fights = self._import_tour(conn, import_id, tour_id, tour_number, sheet, csv_path)
                    summary.fights_imported += imported_fights["fights"]
                    summary.fights_skipped += imported_fights["skipped"]
                    summary.participants_inserted += imported_fights["participants"]
                    summary.questions_inserted += imported_fights["questions"]
                    summary.question_results_inserted += imported_fights["question_results"]
                    if imported_fights["fights"]:
                        summary.tours_imported += 1
                    else:
                        summary.tours_skipped += 1

                self._complete_import(conn, import_id, status="success")
                conn.commit()
            except Exception as exc:  # pragma: no cover - defensive logging
                conn.rollback()
                self._complete_import(conn, import_id, status="failed", message=str(exc))
                conn.commit()
                raise

        return summary

    # Internal helpers ----------------------------------------------

    def _load_manifest(self) -> dict[int, dict[str, str]]:
        data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        tours: dict[int, dict[str, str]] = {}
        for entry in data:
            name = entry.get("name", "")
            if not name:
                continue
            normalized = name.strip().lower()
            if not normalized.startswith("tour"):
                continue
            number_fragment = "".join(ch for ch in name if ch.isdigit())
            if not number_fragment:
                continue
            tour_number = int(number_fragment)
            tours[tour_number] = entry
        return tours

    def _ensure_season(self, conn) -> int:
        row = conn.execute(
            "SELECT id FROM seasons WHERE season_number = ?",
            (self._season_number,),
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO seasons (season_number, slug) VALUES (?, ?)",
                (self._season_number, f"{self._season_number:02d}"),
            )
            return int(cursor.lastrowid)
        return int(row[0])

    def _ensure_tour(self, conn, season_id: int, tour_number: int, gid: Optional[str]) -> int:
        row = conn.execute(
            "SELECT id FROM tours WHERE season_id = ? AND tour_number = ?",
            (season_id, tour_number),
        ).fetchone()
        if row is not None:
            tour_id = int(row[0])
            if gid:
                conn.execute(
                    "UPDATE tours SET gid = ? WHERE id = ?",
                    (int(gid), tour_id),
                )
            return tour_id

        cursor = conn.execute(
            "INSERT INTO tours (season_id, tour_number, gid) VALUES (?, ?, ?)",
            (season_id, tour_number, int(gid) if gid else None),
        )
        return int(cursor.lastrowid)

    def _create_import_record(self, conn) -> int:
        started_at = time.time()
        cursor = conn.execute(
            (
                "INSERT INTO imports (source, source_identifier, season_number, started_at, status) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (
                self._source,
                str(self._manifest_path),
                self._season_number,
                started_at,
                "running",
            ),
        )
        return int(cursor.lastrowid)

    def _complete_import(self, conn, import_id: int, *, status: str, message: Optional[str] = None) -> None:
        conn.execute(
            "UPDATE imports SET finished_at = ?, status = ?, message = COALESCE(?, message) WHERE id = ?",
            (time.time(), status, message, import_id),
        )

    def _import_tour(
        self,
        conn,
        import_id: int,
        tour_id: int,
        tour_number: int,
        sheet: Season2TourSheet,
        csv_path: Path,
    ) -> dict[str, int]:
        stats = {
            "fights": 0,
            "skipped": 0,
            "participants": 0,
            "questions": 0,
            "question_results": 0,
        }

        for fight in sheet.iter_fights():
            fight_code = f"S{self._season_number:02d}E{tour_number:02d}F{fight.ordinal:02d}"

            conn.execute("DELETE FROM fights WHERE fight_code = ?", (fight_code,))

            cursor = conn.execute(
                (
                    "INSERT INTO fights (tour_id, fight_number, ordinal, fight_code, imported_at, source_path, import_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    tour_id,
                    fight.ordinal,
                    fight.ordinal,
                    fight_code,
                    time.time(),
                    str(csv_path),
                    import_id,
                ),
            )
            fight_id = int(cursor.lastrowid)

            participant_ids = self._insert_participants(
                conn,
                fight_id,
                tour_number,
                fight,
            )
            stats["participants"] += len(participant_ids)

            inserted_questions = self._insert_questions(conn, fight_id, fight, participant_ids)
            stats["questions"] += inserted_questions["questions"]
            stats["question_results"] += inserted_questions["question_results"]
            stats["fights"] += 1

        return stats

    def _insert_participants(
        self,
        conn,
        fight_id: int,
        tour_number: int,
        fight: Season2Fight,
    ) -> list[int]:
        participant_ids: list[int] = []
        for seat_index, total in enumerate(fight.player_totals):
            display_name = f"Seat {seat_index + 1}"
            normalized_name = self._normalize_placeholder_name(tour_number, fight.ordinal, seat_index)
            cursor = conn.execute(
                (
                    "INSERT INTO fight_participants (fight_id, display_name, normalized_name, seat_index, total_score) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (
                    fight_id,
                    display_name,
                    normalized_name,
                    seat_index + 1,
                    total,
                ),
            )
            participant_ids.append(int(cursor.lastrowid))
        return participant_ids

    def _insert_questions(
        self,
        conn,
        fight_id: int,
        fight: Season2Fight,
        participant_ids: Sequence[int],
    ) -> dict[str, int]:
        stats = {"questions": 0, "question_results": 0}
        for order, question in enumerate(fight.questions, start=1):
            cursor = conn.execute(
                (
                    "INSERT INTO questions (fight_id, question_order, nominal, theme, source_row) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (
                    fight_id,
                    order,
                    question.nominal,
                    None,
                    question.source_row,
                ),
            )
            question_id = int(cursor.lastrowid)
            stats["questions"] += 1

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

    def _normalize_placeholder_name(self, tour_number: int, fight_ordinal: int, seat_index: int) -> str:
        return f"s{self._season_number:02d}e{tour_number:02d}f{fight_ordinal:02d}_seat{seat_index + 1}"


__all__ = ["Season2Importer", "Season2ImportSummary"]

