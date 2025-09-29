import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency for Postgres deployments
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional dependency for Postgres deployments
    psycopg2 = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


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

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        enable_sample_data: Optional[bool] = None,
    ) -> None:
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
        if enable_sample_data is None:
            flag = os.getenv("PANENKA_ENABLE_SAMPLE_DATA")
            if flag is None:
                enable_sample_data = True
            else:
                enable_sample_data = flag.lower() in {"1", "true", "yes", "on"}
        self._enable_sample_data = enable_sample_data

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
            if self._enable_sample_data:
                self._seed_from_fixture_sqlite(conn)

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
                if self._enable_sample_data:
                    self._seed_from_fixture_postgres(cur)

    @staticmethod
    def _seed_fixture_path() -> Path:
        return Path(__file__).resolve().parent / "sample_questions.json"

    def _load_seed_records(self) -> List[Tuple[object, ...]]:
        seed_path = self._seed_fixture_path()
        if not seed_path.exists():
            return []

        try:
            with seed_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load sample questions: %s", exc)
            return []

        if not isinstance(payload, list):
            logger.warning(
                "Sample questions file has unexpected structure: %s", type(payload).__name__
            )
            return []

        imported_at = time.time()
        rows: List[Tuple[object, ...]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                logger.warning("Skipping malformed sample question entry: %r", entry)
                continue
            season_number = entry.get("season_number")
            row_number = entry.get("row_number")
            if season_number is None or row_number is None:
                logger.warning(
                    "Skipping sample question without mandatory identifiers: %r", entry
                )
                continue
            rows.append(
                (
                    int(season_number),
                    int(row_number),
                    entry.get("played_at_raw"),
                    entry.get("played_at"),
                    entry.get("editor"),
                    entry.get("topic"),
                    entry.get("question_value"),
                    entry.get("author"),
                    entry.get("question_text"),
                    entry.get("answer_text"),
                    entry.get("taken_count"),
                    entry.get("not_taken_count"),
                    entry.get("comment"),
                    imported_at,
                )
            )

        return rows

    def _seed_from_fixture_sqlite(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("SELECT COUNT(*) FROM questions")
        (existing_total,) = cur.fetchone()
        if existing_total:
            return

        rows = self._load_seed_records()
        if not rows:
            return

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
            rows,
        )
        logger.info("Seeded %d sample question(s) into SQLite store", len(rows))

    def _seed_from_fixture_postgres(self, cur) -> None:  # pragma: no cover - exercised in production
        cur.execute("SELECT COUNT(*) AS total FROM questions")
        row = cur.fetchone() or {}
        existing_total = row.get("total", 0)
        if existing_total:
            return

        rows = self._load_seed_records()
        if not rows:
            return

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
            rows,
            page_size=50,
        )
        logger.info("Seeded %d sample question(s) into Postgres store", len(rows))

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


    def search_questions(
        self,
        keywords: Optional[Sequence[str]] = None,
        *,
        limit: int = 50,
    ) -> List[Dict[str, object]]:
        """Return question rows filtered by the provided keywords."""

        self._initialize()

        normalized: List[str] = []
        seen = set()
        if keywords:
            for keyword in keywords:
                normalized_keyword = keyword.strip().lower()
                if normalized_keyword and normalized_keyword not in seen:
                    normalized.append(normalized_keyword)
                    seen.add(normalized_keyword)

        limit = max(1, min(limit, 200))
        placeholder = "?" if self._backend == "sqlite" else "%s"
        keyword_clauses: List[str] = []
        params: List[object] = []
        search_fields = [
            "question_text",
            "answer_text",
            "topic",
            "author",
        ]

        for keyword in normalized:
            variations = []
            seen_variations = set()
            for variant in (
                keyword,
                keyword.lower(),
                keyword.upper(),
                keyword.capitalize(),
                keyword.title(),
            ):
                if not variant:
                    continue
                if variant in seen_variations:
                    continue
                seen_variations.add(variant)
                variations.append(variant)

            keyword_conditions = []
            for variant in variations:
                pattern = f"%{variant}%"
                for field in search_fields:
                    keyword_conditions.append(
                        f"COALESCE({field}, '') LIKE {placeholder}"
                    )
                    params.append(pattern)

            if keyword_conditions:
                keyword_clauses.append("(" + " OR ".join(keyword_conditions) + ")")

        limit_placeholder = "?" if self._backend == "sqlite" else "%s"
        sql = [
            "SELECT",
            "    id,",
            "    season_number,",
            "    row_number,",
            "    topic,",
            "    question_value,",
            "    author,",
            "    editor,",
            "    question_text,",
            "    answer_text,",
            "    played_at_raw,",
            "    played_at",
            "FROM questions",
        ]
        if keyword_clauses:
            sql.append("WHERE " + " OR ".join(keyword_clauses))
        sql.append("ORDER BY imported_at DESC")
        sql.append(f"LIMIT {limit_placeholder}")

        query = "\n".join(sql)
        params_with_limit = params + [limit]

        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                cur = conn.execute(query, params_with_limit)
                rows = cur.fetchall()
                return [dict(row) for row in rows]

        if psycopg2 is None:
            raise RuntimeError("psycopg2 must be installed for PostgreSQL support.")

        with self._postgres_connection() as conn:  # pragma: no cover - production
            with conn.cursor() as cur:
                cur.execute(query, params_with_limit)
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def list_questions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        season_number: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """Return ordered question rows for table views."""

        self._initialize()

        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        placeholder = "?" if self._backend == "sqlite" else "%s"
        sql = [
            "SELECT",
            "    id,",
            "    season_number,",
            "    row_number,",
            "    topic,",
            "    question_value,",
            "    author,",
            "    editor,",
            "    question_text,",
            "    answer_text,",
            "    played_at_raw,",
            "    played_at,",
            "    comment",
            "FROM questions",
        ]
        params: List[object] = []
        if season_number is not None:
            sql.append(f"WHERE season_number = {placeholder}")
            params.append(season_number)
        sql.append("ORDER BY season_number ASC, row_number ASC")
        sql.append(f"LIMIT {placeholder} OFFSET {placeholder}")
        params.extend([limit, offset])

        query = "\n".join(sql)

        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                cur = conn.execute(query, params)
                rows = cur.fetchall()
                return [dict(row) for row in rows]

        if psycopg2 is None:
            raise RuntimeError("psycopg2 must be installed for PostgreSQL support.")

        with self._postgres_connection() as conn:  # pragma: no cover - production
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def get_question_stats(
        self, season_number: Optional[int] = None
    ) -> Dict[str, Optional[object]]:
        """Return aggregate counts and timestamps for stored questions."""

        self._initialize()

        placeholder = "?" if self._backend == "sqlite" else "%s"
        sql = [
            "SELECT",
            "    COUNT(*) AS total,",
            "    MAX(imported_at) AS last_imported_at",
            "FROM questions",
        ]
        params: List[object] = []
        if season_number is not None:
            sql.append(f"WHERE season_number = {placeholder}")
            params.append(season_number)

        query = "\n".join(sql)

        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                cur = conn.execute(query, params)
                row = cur.fetchone()
        else:  # pragma: no cover - production
            if psycopg2 is None:
                raise RuntimeError("psycopg2 must be installed for PostgreSQL support.")
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()

        if not row:
            return {"total": 0, "last_imported_at": None, "season_number": season_number}

        total = row["total"] if isinstance(row, dict) else row[0]
        last_imported_raw = row["last_imported_at"] if isinstance(row, dict) else row[1]
        last_imported_at: Optional[str] = None
        if last_imported_raw:
            try:
                last_imported_at = datetime.fromtimestamp(float(last_imported_raw)).isoformat(
                    timespec="seconds"
                )
            except (TypeError, ValueError, OSError):
                last_imported_at = None

        return {
            "total": int(total or 0),
            "last_imported_at": last_imported_at,
            "season_number": season_number,
        }

    def list_seasons(self) -> List[int]:
        """Return available season numbers in ascending order."""

        self._initialize()

        query = "SELECT DISTINCT season_number FROM questions ORDER BY season_number ASC"

        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                cur = conn.execute(query)
                rows = cur.fetchall()
                return [int(row["season_number"]) for row in rows]

        if psycopg2 is None:
            raise RuntimeError("psycopg2 must be installed for PostgreSQL support.")

        with self._postgres_connection() as conn:  # pragma: no cover - production
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return [int(row["season_number"]) for row in rows]


question_store = QuestionStore()
