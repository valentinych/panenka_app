"""Database bootstrap utilities for storing Season 2 tour results."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class Season2ResultsStore:
    """Manage the database schema used for Season 2 tour results."""

    def __init__(self, db_path: Optional[str] = None, *, enable_season_seed: bool = True) -> None:
        configured_path = db_path or os.getenv("PANENKA_RESULTS_DB")
        if configured_path:
            base_path = Path(configured_path).expanduser()
            if not base_path.is_absolute():
                base_path = (Path.cwd() / base_path).resolve()
            else:
                base_path = base_path.resolve()
        else:
            base_path = Path(__file__).resolve().parent / "season2_results.sqlite3"

        if not base_path.parent.exists():
            base_path.parent.mkdir(parents=True, exist_ok=True)

        self._db_path = str(base_path)
        self._initialized = False
        self._init_lock = threading.Lock()
        self._enable_season_seed = enable_season_seed

    @property
    def db_path(self) -> str:
        return self._db_path

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._initialize_sqlite()
            self._initialized = True

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.ensure_schema()
        conn = self._connect_sqlite()
        try:
            yield conn
        finally:
            conn.close()

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level="DEFERRED",
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            self._create_tables(conn)
            if self._enable_season_seed:
                self._seed_baseline_seasons(conn)

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_number INTEGER NOT NULL UNIQUE,
                slug TEXT NOT NULL UNIQUE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
                tour_number INTEGER NOT NULL,
                gid INTEGER,
                UNIQUE (season_id, tour_number)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_identifier TEXT NOT NULL,
                season_number INTEGER NOT NULL,
                started_at REAL NOT NULL,
                finished_at REAL,
                status TEXT NOT NULL,
                message TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
                fight_number INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                fight_code TEXT NOT NULL UNIQUE,
                imported_at REAL NOT NULL,
                source_path TEXT,
                import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
                UNIQUE (tour_id, fight_number)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fight_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
                display_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                seat_index INTEGER NOT NULL,
                total_score INTEGER NOT NULL,
                UNIQUE (fight_id, normalized_name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
                question_order INTEGER NOT NULL,
                nominal INTEGER NOT NULL,
                theme TEXT,
                source_row INTEGER,
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
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tours_season
                ON tours (season_id, tour_number)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_fights_tour
                ON fights (tour_id, fight_number)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_participants_fight
                ON fight_participants (fight_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_questions_fight
                ON questions (fight_id, question_order)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_results_question
                ON question_results (question_id)
            """
        )

    def _seed_baseline_seasons(self, conn: sqlite3.Connection) -> None:
        for season_number in (1, 2):
            slug = f"{season_number:02d}"
            conn.execute(
                """
                INSERT INTO seasons (season_number, slug)
                VALUES (?, ?)
                ON CONFLICT(season_number) DO NOTHING
                """,
                (season_number, slug),
            )


__all__ = ["Season2ResultsStore"]
