import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional


class LobbyStore:
    """Persist buzzer lobby state in a SQLite database."""

    def __init__(self, db_path: Optional[str] = None) -> None:
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
        self._initialized = False
        self._init_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level="DEFERRED",
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self._connect() as conn:
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
            self._initialized = True

    def clear_all(self) -> None:
        self._initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM players")
            conn.execute("DELETE FROM lobbies")

    def exists(self, code: str) -> bool:
        self._initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM lobbies WHERE code = ?", (code,)).fetchone()
        return row is not None

    def _row_to_lobby(self, row: sqlite3.Row) -> Dict:
        return {
            "code": row["code"],
            "host_id": row["host_id"],
            "host_name": row["host_name"],
            "host_token": row["host_token"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "host_seen": row["host_seen"],
            "locked": bool(row["locked"]),
            "players": {},
            "buzz_order": json.loads(row["buzz_order"] or "[]"),
            "question_value": row["question_value"] if row["question_value"] is not None else 0,
            "active_player_id": row["active_player_id"],
        }

    def get_lobby(self, code: str) -> Optional[Dict]:
        self._initialize()
        with self._connect() as conn:
            lobby_row = conn.execute(
                "SELECT * FROM lobbies WHERE code = ?", (code,)
            ).fetchone()
            if lobby_row is None:
                return None

            lobby = self._row_to_lobby(lobby_row)
            player_rows = conn.execute(
                "SELECT * FROM players WHERE lobby_code = ?", (code,)
            ).fetchall()

        for player in player_rows:
            lobby["players"][player["id"]] = {
                "id": player["id"],
                "name": player["name"],
                "joined_at": player["joined_at"],
                "last_seen": player["last_seen"],
                "buzzed_at": player["buzzed_at"],
                "score": player["score"] if player["score"] is not None else 0,
            }

        return lobby

    def save_lobby(self, lobby: Dict) -> None:
        self._initialize()
        players = lobby.get("players", {})
        buzz_order = lobby.get("buzz_order", [])
        if buzz_order is None:
            buzz_order = []
        with self._connect() as conn:
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

    def delete_lobby(self, code: str) -> None:
        self._initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM lobbies WHERE code = ?", (code,))

    def get_all_lobbies(self) -> List[Dict]:
        self._initialize()
        with self._connect() as conn:
            lobby_rows = conn.execute("SELECT * FROM lobbies").fetchall()
            player_rows = conn.execute("SELECT * FROM players").fetchall()

        lobbies: Dict[str, Dict] = {}
        for row in lobby_rows:
            lobby = self._row_to_lobby(row)
            lobbies[lobby["code"]] = lobby

        for player in player_rows:
            lobby = lobbies.get(player["lobby_code"])
            if lobby is None:
                continue
            lobby["players"][player["id"]] = {
                "id": player["id"],
                "name": player["name"],
                "joined_at": player["joined_at"],
                "last_seen": player["last_seen"],
                "buzzed_at": player["buzzed_at"],
            }

        return list(lobbies.values())


lobby_store = LobbyStore()

