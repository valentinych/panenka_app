from __future__ import annotations

from pathlib import Path

import sqlite3

from app.season2 import Season2Importer, Season2ResultsStore


DATA_ROOT = Path("data/raw/season02/csv")
MANIFEST_PATH = Path("data/raw/season02/manifest.json")


def _import_tour(tmp_path: Path, tour_number: int = 1):
    db_path = tmp_path / "season2.sqlite3"
    store = Season2ResultsStore(db_path=str(db_path))
    importer = Season2Importer(store=store, data_root=DATA_ROOT, manifest_path=MANIFEST_PATH)
    summary = importer.import_season(tours=[tour_number])
    return db_path, summary


def test_importer_loads_fights_into_results_store(tmp_path: Path) -> None:
    db_path, summary = _import_tour(tmp_path, tour_number=1)

    assert summary.fights_imported == 14
    assert summary.questions_inserted == 14 * 5
    assert summary.participants_inserted == 14 * 4

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        fight_row = conn.execute(
            "SELECT id FROM fights WHERE fight_code = ?",
            ("S02E01F03",),
        ).fetchone()
        assert fight_row is not None
        fight_id = fight_row["id"]

        participants = conn.execute(
            "SELECT seat_index, total_score FROM fight_participants WHERE fight_id = ? ORDER BY seat_index",
            (fight_id,),
        ).fetchall()
        assert [row["seat_index"] for row in participants] == [1, 2, 3, 4]
        assert [row["total_score"] for row in participants] == [310, 170, -120, 20]

        questions = conn.execute(
            "SELECT id, question_order, nominal, source_row FROM questions WHERE fight_id = ? ORDER BY question_order",
            (fight_id,),
        ).fetchall()
        assert [row["nominal"] for row in questions] == [10, 20, 30, 40, 50]

        first_question_id = questions[0]["id"]
        results = conn.execute(
            "SELECT delta, is_correct FROM question_results WHERE question_id = ? ORDER BY participant_id",
            (first_question_id,),
        ).fetchall()
        assert [row["delta"] for row in results] == [10, 0, 0, 0]
        assert [row["is_correct"] for row in results] == [1, 0, 0, 0]
    finally:
        conn.close()


def test_import_is_idempotent(tmp_path: Path) -> None:
    db_path, summary_first = _import_tour(tmp_path, tour_number=1)
    assert summary_first.fights_imported == 14

    store = Season2ResultsStore(db_path=str(db_path))
    importer = Season2Importer(store=store, data_root=DATA_ROOT, manifest_path=MANIFEST_PATH)
    summary_second = importer.import_season(tours=[1])
    assert summary_second.fights_imported == 14

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        count = conn.execute("SELECT COUNT(*) FROM fights").fetchone()[0]
        assert count == 14
    finally:
        conn.close()

