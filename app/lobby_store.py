import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

try:  # pragma: no cover - optional dependency for Postgres deployments
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional dependency for Postgres deployments
    psycopg2 = None  # type: ignore[assignment]


class LobbyStore:
    """Persist buzzer lobby state in a SQLite or PostgreSQL database."""

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
                CREATE TABLE IF NOT EXISTS lobbies (
                    code TEXT PRIMARY KEY,
                    host_id TEXT NOT NULL,
                    host_name TEXT NOT NULL,
                    host_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    host_seen REAL NOT NULL,
                    locked INTEGER NOT NULL,
                    buzz_order TEXT NOT NULL,
                    question_value INTEGER NOT NULL DEFAULT 0,
                    active_player_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS players (
                    id TEXT PRIMARY KEY,
                    lobby_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    joined_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    buzzed_at REAL,
                    score INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(lobby_code) REFERENCES lobbies(code) ON DELETE CASCADE
                )
                """
            )
            try:
                conn.execute(
                    "ALTER TABLE players ADD COLUMN score INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE lobbies ADD COLUMN question_value INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "ALTER TABLE lobbies ADD COLUMN active_player_id TEXT"
                )
            except sqlite3.OperationalError:
                pass

    def _initialize_postgres(self) -> None:  # pragma: no cover - exercised in production
        with self._postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lobbies (
                        code TEXT PRIMARY KEY,
                        host_id TEXT NOT NULL,
                        host_name TEXT NOT NULL,
                        host_token TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL,
                        host_seen DOUBLE PRECISION NOT NULL,
                        locked BOOLEAN NOT NULL,
                        buzz_order TEXT NOT NULL,
                        question_value INTEGER NOT NULL DEFAULT 0,
                        active_player_id TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS players (
                        id TEXT PRIMARY KEY,
                        lobby_code TEXT NOT NULL REFERENCES lobbies(code) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        joined_at DOUBLE PRECISION NOT NULL,
                        last_seen DOUBLE PRECISION NOT NULL,
                        buzzed_at DOUBLE PRECISION,
                        score INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(
                    "ALTER TABLE players ADD COLUMN IF NOT EXISTS score INTEGER NOT NULL DEFAULT 0"
                )
                cur.execute(
                    "ALTER TABLE lobbies ADD COLUMN IF NOT EXISTS question_value INTEGER NOT NULL DEFAULT 0"
                )
                cur.execute(
                    "ALTER TABLE lobbies ADD COLUMN IF NOT EXISTS active_player_id TEXT"
                )

    def clear_all(self) -> None:
        self._initialize()
        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                conn.execute("DELETE FROM players")
                conn.execute("DELETE FROM lobbies")
        else:  # pragma: no cover - exercised in production
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM players")
                    cur.execute("DELETE FROM lobbies")

    def exists(self, code: str) -> bool:
        self._initialize()
        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                row = conn.execute(
                    "SELECT 1 FROM lobbies WHERE code = ?", (code,)
                ).fetchone()
                return row is not None
        with self._postgres_connection() as conn:  # pragma: no cover - exercised in production
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM lobbies WHERE code = %s", (code,))
                return cur.fetchone() is not None

    def _row_to_lobby(self, row) -> Dict:
        data = dict(row)
        return {
            "code": data["code"],
            "host_id": data["host_id"],
            "host_name": data["host_name"],
            "host_token": data["host_token"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "host_seen": data["host_seen"],
            "locked": bool(data["locked"]),
            "players": {},
            "buzz_order": json.loads(data["buzz_order"] or "[]"),
            "question_value": data["question_value"] if data["question_value"] is not None else 0,
            "active_player_id": data.get("active_player_id"),
        }

    def get_lobby(self, code: str) -> Optional[Dict]:
        self._initialize()
        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                lobby_row = conn.execute(
                    "SELECT * FROM lobbies WHERE code = ?", (code,)
                ).fetchone()
                if lobby_row is None:
                    return None

                lobby = self._row_to_lobby(lobby_row)
                player_rows = conn.execute(
                    "SELECT * FROM players WHERE lobby_code = ?", (code,)
                ).fetchall()
        else:  # pragma: no cover - exercised in production
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM lobbies WHERE code = %s", (code,))
                    lobby_row = cur.fetchone()
                    if lobby_row is None:
                        return None
                    lobby = self._row_to_lobby(lobby_row)
                    cur.execute("SELECT * FROM players WHERE lobby_code = %s", (code,))
                    player_rows = cur.fetchall()

        for player in player_rows:
            pdata = dict(player)
            lobby["players"][pdata["id"]] = {
                "id": pdata["id"],
                "name": pdata["name"],
                "joined_at": pdata["joined_at"],
                "last_seen": pdata["last_seen"],
                "buzzed_at": pdata.get("buzzed_at"),
                "score": pdata["score"] if pdata["score"] is not None else 0,
            }

        return lobby

    def save_lobby(self, lobby: Dict) -> None:
        self._initialize()
        players = lobby.get("players", {})
        buzz_order = lobby.get("buzz_order", [])
        if buzz_order is None:
            buzz_order = []
        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    INSERT INTO lobbies (
                        code,
                        host_id,
                        host_name,
                        host_token,
                        created_at,
                        updated_at,
                        host_seen,
                        locked,
                        buzz_order,
                        question_value,
                        active_player_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        host_id = excluded.host_id,
                        host_name = excluded.host_name,
                        host_token = excluded.host_token,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        host_seen = excluded.host_seen,
                        locked = excluded.locked,
                        buzz_order = excluded.buzz_order,
                        question_value = excluded.question_value,
                        active_player_id = excluded.active_player_id
                    """,
                    (
                        lobby["code"],
                        lobby["host_id"],
                        lobby["host_name"],
                        lobby["host_token"],
                        lobby["created_at"],
                        lobby["updated_at"],
                        lobby["host_seen"],
                        1 if lobby.get("locked") else 0,
                        json.dumps(buzz_order),
                        int(lobby.get("question_value", 0) or 0),
                        lobby.get("active_player_id"),
                    ),
                )
                conn.execute("DELETE FROM players WHERE lobby_code = ?", (lobby["code"],))
                for player in players.values():
                    conn.execute(
                        """
                        INSERT INTO players (
                            id,
                            lobby_code,
                            name,
                            joined_at,
                            last_seen,
                            buzzed_at,
                            score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            player["id"],
                            lobby["code"],
                            player["name"],
                            player["joined_at"],
                            player["last_seen"],
                            player.get("buzzed_at"),
                            int(player.get("score", 0) or 0),
                        ),
                    )
        else:  # pragma: no cover - exercised in production
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO lobbies (
                            code,
                            host_id,
                            host_name,
                            host_token,
                            created_at,
                            updated_at,
                            host_seen,
                            locked,
                            buzz_order,
                            question_value,
                            active_player_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(code) DO UPDATE SET
                            host_id = EXCLUDED.host_id,
                            host_name = EXCLUDED.host_name,
                            host_token = EXCLUDED.host_token,
                            created_at = EXCLUDED.created_at,
                            updated_at = EXCLUDED.updated_at,
                            host_seen = EXCLUDED.host_seen,
                            locked = EXCLUDED.locked,
                            buzz_order = EXCLUDED.buzz_order,
                            question_value = EXCLUDED.question_value,
                            active_player_id = EXCLUDED.active_player_id
                        """,
                        (
                            lobby["code"],
                            lobby["host_id"],
                            lobby["host_name"],
                            lobby["host_token"],
                            lobby["created_at"],
                            lobby["updated_at"],
                            lobby["host_seen"],
                            bool(lobby.get("locked")),
                            json.dumps(buzz_order),
                            int(lobby.get("question_value", 0) or 0),
                            lobby.get("active_player_id"),
                        ),
                    )
                    cur.execute("DELETE FROM players WHERE lobby_code = %s", (lobby["code"],))
                    for player in players.values():
                        cur.execute(
                            """
                            INSERT INTO players (
                                id,
                                lobby_code,
                                name,
                                joined_at,
                                last_seen,
                                buzzed_at,
                                score
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                player["id"],
                                lobby["code"],
                                player["name"],
                                player["joined_at"],
                                player["last_seen"],
                                player.get("buzzed_at"),
                                int(player.get("score", 0) or 0),
                            ),
                        )

    def delete_lobby(self, code: str) -> None:
        self._initialize()
        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                conn.execute("DELETE FROM lobbies WHERE code = ?", (code,))
        else:  # pragma: no cover - exercised in production
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM lobbies WHERE code = %s", (code,))

    def get_all_lobbies(self) -> List[Dict]:
        self._initialize()
        if self._backend == "sqlite":
            with self._connect_sqlite() as conn:
                lobby_rows = conn.execute("SELECT * FROM lobbies").fetchall()
                player_rows = conn.execute("SELECT * FROM players").fetchall()
        else:  # pragma: no cover - exercised in production
            with self._postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM lobbies")
                    lobby_rows = cur.fetchall()
                    cur.execute("SELECT * FROM players")
                    player_rows = cur.fetchall()

        lobbies: Dict[str, Dict] = {}
        for row in lobby_rows:
            lobby = self._row_to_lobby(row)
            lobbies[lobby["code"]] = lobby

        for player in player_rows:
            pdata = dict(player)
            lobby = lobbies.get(pdata["lobby_code"])
            if lobby is None:
                continue
            lobby["players"][pdata["id"]] = {
                "id": pdata["id"],
                "name": pdata["name"],
                "joined_at": pdata["joined_at"],
                "last_seen": pdata["last_seen"],
                "buzzed_at": pdata.get("buzzed_at"),
            }

        return list(lobbies.values())


lobby_store = LobbyStore()

