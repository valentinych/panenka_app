from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.tour_statistics_store import TourStatisticsStore


def _create_basic_records(conn: sqlite3.Connection) -> dict[str, int]:
    season_id = conn.execute(
        "INSERT INTO seasons (season_number, code) VALUES (?, ?)",
        (1, "S01"),
    ).lastrowid
    tour_id = conn.execute(
        "INSERT INTO tours (season_id, tour_number, code) VALUES (?, ?, ?)",
        (season_id, 2, "S01E02"),
    ).lastrowid
    import_id = conn.execute(
        """
        INSERT INTO imports (source, source_identifier, sheet_name, started_at, status)
        VALUES (?, ?, ?, datetime('now'), 'pending')
        """,
        ("google_sheets", "dummy", "S01E02"),
    ).lastrowid
    theme_id = conn.execute(
        "INSERT INTO themes (title) VALUES (?)",
        ("Цветная",),
    ).lastrowid
    player_id = conn.execute(
        """
        INSERT INTO players (full_name, normalized_name) VALUES (?, ?)
        """,
        ("Мария Тимохова", "мария тимохова"),
    ).lastrowid
    alias_id = conn.execute(
        """
        INSERT INTO player_aliases (player_id, alias, normalized_alias)
        VALUES (?, ?, ?)
        """,
        (player_id, "Мария Тимохова", "мария тимохова"),
    ).lastrowid
    fight_id = conn.execute(
        """
        INSERT INTO fights (
            tour_id, fight_number, fight_code, sheet_column_range,
            question_row_start, question_row_end, import_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tour_id, 1, "S01E02F01", "B:G", 5, 54, import_id),
    ).lastrowid
    participant_id = conn.execute(
        """
        INSERT INTO fight_participants (
            fight_id, player_id, seat_index, total_score
        ) VALUES (?, ?, ?, ?)
        """,
        (fight_id, player_id, 1, 30),
    ).lastrowid

    question_ids: list[int] = []
    for order, nominal in enumerate((10, 10, 10), start=1):
        question_id = conn.execute(
            """
            INSERT INTO questions (fight_id, theme_id, question_order, nominal, sheet_row)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fight_id, theme_id, order, nominal, order + 4),
        ).lastrowid
        question_ids.append(question_id)

    return {
        "season_id": int(season_id),
        "tour_id": int(tour_id),
        "import_id": int(import_id),
        "theme_id": int(theme_id),
        "player_id": int(player_id),
        "alias_id": int(alias_id),
        "fight_id": int(fight_id),
        "participant_id": int(participant_id),
        "question_ids": [int(qid) for qid in question_ids],
    }


def test_schema_initialisation_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "tour_stats.sqlite3"
    store = TourStatisticsStore(db_path=str(db_path))

    store.ensure_schema()

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    expected_tables = {
        "seasons",
        "tours",
        "imports",
        "players",
        "player_aliases",
        "themes",
        "fights",
        "fight_participants",
        "questions",
        "question_results",
    }

    assert expected_tables.issubset(tables)


def test_reset_all_data_clears_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "tour_stats.sqlite3"
    store = TourStatisticsStore(db_path=str(db_path))

    with store.connection() as conn:
        references = _create_basic_records(conn)
        for question_id in references["question_ids"]:
            conn.execute(
                """
                INSERT INTO question_results (question_id, participant_id, delta, is_correct)
                VALUES (?, ?, ?, ?)
                """,
                (question_id, references["participant_id"], 10, 1),
            )

        store.reset_all_data(conn)

        for table in (
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
        ):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0


def test_question_result_trigger_validates_totals(tmp_path: Path) -> None:
    db_path = tmp_path / "tour_stats.sqlite3"
    store = TourStatisticsStore(db_path=str(db_path))

    with store.connection() as conn:
        refs = _create_basic_records(conn)

        # Insert three question results that sum to the participant total.
        deltas = (10, 10, 10)
        for question_id, delta in zip(refs["question_ids"], deltas):
            conn.execute(
                """
                INSERT INTO question_results (question_id, participant_id, delta, is_correct)
                VALUES (?, ?, ?, ?)
                """,
                (question_id, refs["participant_id"], delta, 1 if delta > 0 else 0),
            )

        # Updating one of the deltas should now violate the trigger because the
        # counts match and the sums diverge from total_score.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE question_results SET delta = ? WHERE question_id = ?",
                (20, refs["question_ids"][0]),
            )

        # The original values remain in place after the failed update.
        results = conn.execute(
            "SELECT delta FROM question_results ORDER BY question_id",
        ).fetchall()
        assert [row[0] for row in results] == [10, 10, 10]


def test_indexes_created(tmp_path: Path) -> None:
    db_path = tmp_path / "tour_stats.sqlite3"
    store = TourStatisticsStore(db_path=str(db_path))

    store.ensure_schema()

    conn = sqlite3.connect(db_path)
    try:
        alias_indexes = {
            row[1]
            for row in conn.execute(
                "PRAGMA index_list('player_aliases')"
            ).fetchall()
        }
        results_indexes = {
            row[1]
            for row in conn.execute(
                "PRAGMA index_list('question_results')"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "idx_player_aliases_normalized" in alias_indexes
    assert "idx_question_results_participant" in results_indexes

