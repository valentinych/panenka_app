import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional, Tuple

try:  # pragma: no cover - optional dependency for Postgres deployments
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional dependency for Postgres deployments
    psycopg2 = None  # type: ignore[assignment]


QuestionRecord = Tuple[
    int,
    int,
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[int],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[int],
    Optional[int],
    Optional[str],
]


class QuestionStore:
    """Persist parsed questions in a SQLite or PostgreSQL database."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        db_url: Optional[str] = None
        if db_path is None:
            db_url = os.getenv("PANENKA_LOBBY_DB_URL") or os.getenv("DATABASE_URL")

        if db_url:
            if psycopg2 is None:
                raise RuntimeError(
                    "psycopg2 is required for PostgreSQL support but is not installed."
                )
            self._backend = "postgres"
            self._db_url = self._normalize_postgres_url(db_url)
            self._db_path = None
        else:
            configured_path = db_path or os.getenv("PANENKA_LOBBY_DB")
            if configured_path:
                base_path = Path(configured_path).expanduser()
                if not base_path.is_absolute():
                    base_path = (Path.cwd() / base_path).resolve()
                else:
                    base_path = base_path.resolve()
            else:
                base_path = Path(__file__).resolve().parent / "lobbies.sqlite3"

            if not base_path.parent.exists():
                base_path.parent.mkdir(parents=True, exist_ok=True)

            self._db_path = str(base_path)
            self._backend = "sqlite"
        self._initialized = False
        self._init_lock = threading.Lock()

    @staticmethod
    def _normalize_postgres_url(url: str) -> str:
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://") :]
        return url

    def _connect_sqlite(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("SQLite backend not configured.")
        conn = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level="DEFERRED",
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _postgres_connection(self):  # pragma: no cover - exercised in production
        if psycopg2 is None:
            raise RuntimeError("psycopg2 must be installed for PostgreSQL support.")
        if self._backend != "postgres":
            raise RuntimeError("PostgreSQL connection requested for non-Postgres backend.")
        conn = psycopg2.connect(
            self._db_url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            if self._backend == "sqlite":
                self._initialize_sqlite()
            else:
                self._initialize_postgres()
            self._initialized = True

    def _initialize_sqlite(self) -> None:
        with self._connect_sqlite() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    season_number INTEGER NOT NULL,
                    row_number INTEGER NOT NULL,
                    played_at_raw TEXT,
                    played_at TEXT,
                    editor TEXT,
                    topic TEXT,
                    question_value INTEGER,
                    author TEXT,
                    question_text TEXT,
                    answer_text TEXT,
                    taken_count INTEGER,
                    not_taken_count INTEGER,
                    comment TEXT,
                    imported_at REAL NOT NULL,
                    UNIQUE (season_number, row_number)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_questions_season
                    ON questions (season_number)
                """
            )

    def _initialize_postgres(self) -> None:  # pragma: no cover - exercised in production
        with self._postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS questions (
                        id BIGSERIAL PRIMARY KEY,
                        season_number INTEGER NOT NULL,
                        row_number INTEGER NOT NULL,
                        played_at_raw TEXT,
                        played_at DATE,
                        editor TEXT,
                        topic TEXT,
                        question_value INTEGER,
                        author TEXT,
                        question_text TEXT,
                        answer_text TEXT,
                        taken_count INTEGER,
                        not_taken_count INTEGER,
                        comment TEXT,
                        imported_at DOUBLE PRECISION NOT NULL,
                        UNIQUE (season_number, row_number)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_questions_season
                        ON questions (season_number)
                    """
                )

    def replace_all(self, records: Iterable[QuestionRecord]) -> int:
        """Replace all stored questions with the provided records."""

        self._initialize()
        payloads = list(records)
        if not payloads:
            return 0
        imported_at = time.time()

        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                conn.execute("DELETE FROM questions")
                conn.executemany(
                    """
                    INSERT INTO questions (
                        season_number,
                        row_number,
                        played_at_raw,
                        played_at,
                        editor,
                        topic,
                        question_value,
                        author,
                        question_text,
                        answer_text,
                        taken_count,
                        not_taken_count,
                        comment,
                        imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [tuple(list(record) + [imported_at]) for record in payloads],
                )
        else:  # pragma: no cover - exercised in production
            if psycopg2 is None:
                raise RuntimeError("psycopg2 must be installed for PostgreSQL support.")
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM questions")
                    psycopg2.extras.execute_batch(
                        cur,
                        """
                        INSERT INTO questions (
                            season_number,
                            row_number,
                            played_at_raw,
                            played_at,
                            editor,
                            topic,
                            question_value,
                            author,
                            question_text,
                            answer_text,
                            taken_count,
                            not_taken_count,
                            comment,
                            imported_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            record + (imported_at,)  # type: ignore[operator]
                            for record in payloads
                        ],
                        page_size=200,
                    )
        return len(payloads)


question_store = QuestionStore()
