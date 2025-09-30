from __future__ import annotations

import sqlite3
from pathlib import Path

from app.season2 import Season2ResultsStore


def test_ensure_schema_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "results.sqlite3"
    store = Season2ResultsStore(db_path=str(db_path))

    store.ensure_schema()

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        }
    finally:
        conn.close()

    expected = {
        "fights",
        "fight_participants",
        "imports",
        "question_results",
        "questions",
        "seasons",
        "sqlite_sequence",
        "tours",
    }
    assert expected.issubset(tables)


def test_baseline_seasons_seeded(tmp_path: Path) -> None:
    db_path = tmp_path / "results.sqlite3"
    store = Season2ResultsStore(db_path=str(db_path))

    store.ensure_schema()
    store.ensure_schema()  # idempotent

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT season_number, slug FROM seasons ORDER BY season_number"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [(1, "01"), (2, "02")]
