import json
import os
import threading
from typing import Dict, List, Optional
from urllib.parse import urlparse
import logging

# Попытка импорта PostgreSQL драйвера
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# Fallback на SQLite
import sqlite3
from pathlib import Path


class LobbyStore:
    """Persist buzzer lobby state in PostgreSQL (Heroku) or SQLite (local)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._initialized = False
        self._init_lock = threading.Lock()
        self._use_postgres = False
        self._db_url = None
        self._db_path = None
        
        # Проверяем DATABASE_URL (Heroku PostgreSQL)
        database_url = os.getenv("DATABASE_URL")
        if database_url and POSTGRES_AVAILABLE:
            self._use_postgres = True
            self._db_url = database_url
            logging.info("Using PostgreSQL from DATABASE_URL")
        else:
            # Fallback на SQLite
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
            logging.info(f"Using SQLite at {self._db_path}")

    def _connect_postgres(self):
        """Connect to PostgreSQL database."""
        return psycopg2.connect(
            self._db_url,
            cursor_factory=psycopg2.extras.RealDictCursor
        )

    def _connect_sqlite(self):
        """Connect to SQLite database."""
        conn = sqlite3.connect(
            self._db_path,
            timeout=30,
            isolation_level="DEFERRED",
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _connect(self):
        """Connect to appropriate database."""
        if self._use_postgres:
            return self._connect_postgres()
        else:
            return self._connect_sqlite()

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            
            if self._use_postgres:
                self._initialize_postgres()
            else:
                self._initialize_sqlite()
            
            self._initialized = True

    def _initialize_postgres(self) -> None:
        """Initialize PostgreSQL tables."""
        with self._connect_postgres() as conn:
            with conn.cursor() as cur:
                # Create lobbies table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS lobbies (
                        code TEXT PRIMARY KEY,
                        host_id TEXT NOT NULL,
                        host_name TEXT NOT NULL,
                        host_token TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        host_seen REAL NOT NULL,
                        locked BOOLEAN NOT NULL DEFAULT FALSE,
                        buzz_order TEXT NOT NULL DEFAULT '[]'
                    )
                """)
                
                # Create players table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS players (
                        id TEXT PRIMARY KEY,
                        lobby_code TEXT NOT NULL,
                        name TEXT NOT NULL,
                        joined_at REAL NOT NULL,
                        last_seen REAL NOT NULL,
                        buzzed_at REAL,
                        FOREIGN KEY(lobby_code) REFERENCES lobbies(code) ON DELETE CASCADE
                    )
                """)
                
                # Create index for better performance
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_players_lobby_code 
                    ON players(lobby_code)
                """)
                
                conn.commit()

    def _initialize_sqlite(self) -> None:
        """Initialize SQLite tables."""
        with self._connect_sqlite() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lobbies (
                    code TEXT PRIMARY KEY,
                    host_id TEXT NOT NULL,
                    host_name TEXT NOT NULL,
                    host_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    host_seen REAL NOT NULL,
                    locked INTEGER NOT NULL,
                    buzz_order TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    id TEXT PRIMARY KEY,
                    lobby_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    joined_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    buzzed_at REAL,
                    FOREIGN KEY(lobby_code) REFERENCES lobbies(code) ON DELETE CASCADE
                )
            """)

    def clear_all(self) -> None:
        self._initialize()
        with self._connect() as conn:
            if self._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM players")
                    cur.execute("DELETE FROM lobbies")
                    conn.commit()
            else:
                conn.execute("DELETE FROM players")
                conn.execute("DELETE FROM lobbies")

    def exists(self, code: str) -> bool:
        self._initialize()
        with self._connect() as conn:
            if self._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM lobbies WHERE code = %s", (code,))
                    return cur.fetchone() is not None
            else:
                row = conn.execute("SELECT 1 FROM lobbies WHERE code = ?", (code,)).fetchone()
                return row is not None

    def _row_to_lobby(self, row) -> Dict:
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
        }

    def get_lobby(self, code: str) -> Optional[Dict]:
        self._initialize()
        with self._connect() as conn:
            if self._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM lobbies WHERE code = %s", (code,))
                    lobby_row = cur.fetchone()
                    if lobby_row is None:
                        return None

                    lobby = self._row_to_lobby(lobby_row)
                    cur.execute("SELECT * FROM players WHERE lobby_code = %s", (code,))
                    player_rows = cur.fetchall()
            else:
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
            }

        return lobby

    def save_lobby(self, lobby: Dict) -> None:
        self._initialize()
        players = lobby.get("players", {})
        buzz_order = lobby.get("buzz_order", [])
        if buzz_order is None:
            buzz_order = []

        with self._connect() as conn:
            if self._use_postgres:
                with conn.cursor() as cur:
                    # Upsert lobby
                    cur.execute("""
                        INSERT INTO lobbies (
                            code, host_id, host_name, host_token,
                            created_at, updated_at, host_seen, locked, buzz_order
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(code) DO UPDATE SET
                            host_id = EXCLUDED.host_id,
                            host_name = EXCLUDED.host_name,
                            host_token = EXCLUDED.host_token,
                            created_at = EXCLUDED.created_at,
                            updated_at = EXCLUDED.updated_at,
                            host_seen = EXCLUDED.host_seen,
                            locked = EXCLUDED.locked,
                            buzz_order = EXCLUDED.buzz_order
                    """, (
                        lobby["code"], lobby["host_id"], lobby["host_name"],
                        lobby["host_token"], lobby["created_at"], lobby["updated_at"],
                        lobby["host_seen"], lobby.get("locked", False),
                        json.dumps(buzz_order)
                    ))
                    
                    # Delete old players and insert new ones
                    cur.execute("DELETE FROM players WHERE lobby_code = %s", (lobby["code"],))
                    for player in players.values():
                        cur.execute("""
                            INSERT INTO players (
                                id, lobby_code, name, joined_at, last_seen, buzzed_at
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            player["id"], lobby["code"], player["name"],
                            player["joined_at"], player["last_seen"],
                            player.get("buzzed_at")
                        ))
                    conn.commit()
            else:
                # SQLite version
                conn.execute("""
                    INSERT INTO lobbies (
                        code, host_id, host_name, host_token,
                        created_at, updated_at, host_seen, locked, buzz_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        host_id = excluded.host_id,
                        host_name = excluded.host_name,
                        host_token = excluded.host_token,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        host_seen = excluded.host_seen,
                        locked = excluded.locked,
                        buzz_order = excluded.buzz_order
                """, (
                    lobby["code"], lobby["host_id"], lobby["host_name"],
                    lobby["host_token"], lobby["created_at"], lobby["updated_at"],
                    lobby["host_seen"], 1 if lobby.get("locked") else 0,
                    json.dumps(buzz_order)
                ))
                
                conn.execute("DELETE FROM players WHERE lobby_code = ?", (lobby["code"],))
                for player in players.values():
                    conn.execute("""
                        INSERT INTO players (
                            id, lobby_code, name, joined_at, last_seen, buzzed_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        player["id"], lobby["code"], player["name"],
                        player["joined_at"], player["last_seen"],
                        player.get("buzzed_at")
                    ))

    def delete_lobby(self, code: str) -> None:
        self._initialize()
        with self._connect() as conn:
            if self._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM lobbies WHERE code = %s", (code,))
                    conn.commit()
            else:
                conn.execute("DELETE FROM lobbies WHERE code = ?", (code,))

    def get_all_lobbies(self) -> List[Dict]:
        self._initialize()
        with self._connect() as conn:
            if self._use_postgres:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM lobbies")
                    lobby_rows = cur.fetchall()
                    cur.execute("SELECT * FROM players")
                    player_rows = cur.fetchall()
            else:
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


# Создаем глобальный экземпляр
lobby_store = LobbyStore()
