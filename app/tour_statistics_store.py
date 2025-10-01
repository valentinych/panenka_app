"""SQLite-backed storage for detailed tour statistics.

This module implements the database scaffolding described in
``docs/tour_statistics_import.md``.  It focuses on the first three stages of
the import pipeline:

1. Cleaning previously imported data so the new schema starts from a blank
   slate.
2. Creating the normalized tables for seasons, tours, fights, players and the
   per-question statistics.
3. Provisioning supporting indexes and integrity triggers that keep
   participant totals in sync with per-question deltas.

Subsequent stages (loading reference data and ingesting Google Sheets exports)
can build on top of this storage layer.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class TourStatisticsStore:
    """Manage the SQLite database used for tour statistics imports."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        configured_path = db_path or os.getenv("PANENKA_TOUR_STATS_DB")
        if configured_path:
            base_path = Path(configured_path).expanduser()
            if not base_path.is_absolute():
                base_path = (Path.cwd() / base_path).resolve()
            else:
                base_path = base_path.resolve()
        else:
            base_path = Path(__file__).resolve().parent / "tour_statistics.sqlite3"

        if not base_path.parent.exists():
            base_path.parent.mkdir(parents=True, exist_ok=True)

        self._db_path = str(base_path)
        self._initialized = False
        self._init_lock = threading.Lock()

    @property
    def db_path(self) -> str:
        return self._db_path

    def ensure_schema(self) -> None:
        """Create the schema if it does not exist yet."""

        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._initialise_sqlite()
            self._initialized = True

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection with foreign keys enabled."""

        self.ensure_schema()
        conn = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level="DEFERRED",
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Schema management helpers

    def _initialise_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            self._create_tables(conn)
            self._create_indexes(conn)
            self._create_triggers(conn)

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level="DEFERRED",
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_number INTEGER NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
                tour_number INTEGER NOT NULL,
                code TEXT NOT NULL,
                UNIQUE (season_id, tour_number),
                UNIQUE (code)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_identifier TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                message TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL UNIQUE,
                normalized_name TEXT NOT NULL UNIQUE,
                gender TEXT,
                city TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS player_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                UNIQUE (player_id, normalized_alias),
                UNIQUE (alias)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE,
                external_code TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
                fight_number INTEGER NOT NULL,
                fight_code TEXT NOT NULL UNIQUE,
                sheet_column_range TEXT NOT NULL,
                question_row_start INTEGER NOT NULL,
                question_row_end INTEGER NOT NULL,
                import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (tour_id, fight_number)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fight_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
                player_id INTEGER NOT NULL REFERENCES players(id),
                seat_index INTEGER NOT NULL,
                total_score INTEGER NOT NULL,
                finishing_place INTEGER,
                UNIQUE (fight_id, player_id),
                UNIQUE (fight_id, seat_index)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
                theme_id INTEGER NOT NULL REFERENCES themes(id),
                question_order INTEGER NOT NULL,
                nominal INTEGER NOT NULL,
                sheet_row INTEGER NOT NULL,
                UNIQUE (fight_id, question_order)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS question_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                participant_id INTEGER NOT NULL REFERENCES fight_participants(id) ON DELETE CASCADE,
                delta INTEGER NOT NULL,
                is_correct INTEGER NOT NULL,
                UNIQUE (question_id, participant_id)
            )
            """
        )

    def _create_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_player_aliases_normalized
                ON player_aliases (normalized_alias)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_question_results_participant
                ON question_results (participant_id)
            """
        )

    def _create_triggers(self, conn: sqlite3.Connection) -> None:
        mismatch_message = (
            "question_results totals do not match fight_participants.total_score"
        )

        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_question_results_check_insert
            AFTER INSERT ON question_results
            BEGIN
                SELECT CASE
                    WHEN (
                        SELECT COUNT(*) FROM question_results
                        WHERE participant_id = NEW.participant_id
                    ) = (
                        SELECT COUNT(*) FROM questions
                        WHERE fight_id = (
                            SELECT fight_id FROM fight_participants
                            WHERE id = NEW.participant_id
                        )
                    )
                    AND (
                        SELECT COALESCE(SUM(delta), 0) FROM question_results
                        WHERE participant_id = NEW.participant_id
                    ) != (
                        SELECT total_score FROM fight_participants
                        WHERE id = NEW.participant_id
                    )
                    THEN RAISE(ABORT, '{mismatch_message}')
                END;
            END;
            """
        )

        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_question_results_check_update
            AFTER UPDATE ON question_results
            BEGIN
                SELECT CASE
                    WHEN (
                        SELECT COUNT(*) FROM question_results
                        WHERE participant_id = NEW.participant_id
                    ) = (
                        SELECT COUNT(*) FROM questions
                        WHERE fight_id = (
                            SELECT fight_id FROM fight_participants
                            WHERE id = NEW.participant_id
                        )
                    )
                    AND (
                        SELECT COALESCE(SUM(delta), 0) FROM question_results
                        WHERE participant_id = NEW.participant_id
                    ) != (
                        SELECT total_score FROM fight_participants
                        WHERE id = NEW.participant_id
                    )
                    THEN RAISE(ABORT, '{mismatch_message}')
                END;

                SELECT CASE
                    WHEN NEW.participant_id <> OLD.participant_id
                    AND (
                        SELECT COUNT(*) FROM question_results
                        WHERE participant_id = OLD.participant_id
                    ) = (
                        SELECT COUNT(*) FROM questions
                        WHERE fight_id = (
                            SELECT fight_id FROM fight_participants
                            WHERE id = OLD.participant_id
                        )
                    )
                    AND (
                        SELECT COALESCE(SUM(delta), 0) FROM question_results
                        WHERE participant_id = OLD.participant_id
                    ) != (
                        SELECT total_score FROM fight_participants
                        WHERE id = OLD.participant_id
                    )
                    THEN RAISE(ABORT, '{mismatch_message}')
                END;
            END;
            """
        )

        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_question_results_check_delete
            AFTER DELETE ON question_results
            BEGIN
                SELECT CASE
                    WHEN (
                        SELECT COUNT(*) FROM question_results
                        WHERE participant_id = OLD.participant_id
                    ) = (
                        SELECT COUNT(*) FROM questions
                        WHERE fight_id = (
                            SELECT fight_id FROM fight_participants
                            WHERE id = OLD.participant_id
                        )
                    )
                    AND (
                        SELECT COALESCE(SUM(delta), 0) FROM question_results
                        WHERE participant_id = OLD.participant_id
                    ) != (
                        SELECT total_score FROM fight_participants
                        WHERE id = OLD.participant_id
                    )
                    THEN RAISE(ABORT, '{mismatch_message}')
                END;
            END;
            """
        )

        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_fight_participants_score_check
            AFTER UPDATE OF total_score ON fight_participants
            BEGIN
                SELECT CASE
                    WHEN (
                        SELECT COUNT(*) FROM question_results
                        WHERE participant_id = NEW.id
                    ) = (
                        SELECT COUNT(*) FROM questions
                        WHERE fight_id = NEW.fight_id
                    )
                    AND (
                        SELECT COALESCE(SUM(delta), 0) FROM question_results
                        WHERE participant_id = NEW.id
                    ) != NEW.total_score
                    THEN RAISE(ABORT, '{mismatch_message}')
                END;
            END;
            """
        )

    # ------------------------------------------------------------------
    # Stage 1 helper

    def reset_all_data(self, conn: sqlite3.Connection) -> None:
        """Delete data from all statistics tables (stage 1)."""

        tables = [
            "question_results",
            "questions",
            "fight_participants",
            "fights",
            "tours",
            "seasons",
            "imports",
            "player_aliases",
            "players",
            "themes",
        ]
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name = ?",
                (table,),
            )


__all__ = ["TourStatisticsStore"]

