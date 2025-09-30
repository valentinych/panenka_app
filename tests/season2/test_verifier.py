from __future__ import annotations

from pathlib import Path

import sqlite3

import pytest

from app.season2 import (
    Season2Importer,
    Season2ResultsStore,
    Season2ResultsVerifier,
    Season2VerificationError,
)

DATA_ROOT = Path("data/raw/season02/csv")
MANIFEST_PATH = Path("data/raw/season02/manifest.json")


def _import_sample_tour(tmp_path: Path, tour_number: int = 1) -> Season2ResultsStore:
    db_path = tmp_path / "season2.sqlite3"
    store = Season2ResultsStore(db_path=str(db_path))
    importer = Season2Importer(store=store, data_root=DATA_ROOT, manifest_path=MANIFEST_PATH)
    importer.import_season(tours=[tour_number])
    return Season2ResultsStore(db_path=str(db_path))


def test_verifier_reports_existing_discrepancies(tmp_path: Path) -> None:
    store = _import_sample_tour(tmp_path, tour_number=1)
    verifier = Season2ResultsVerifier(store=store)

    report = verifier.verify()

    assert not report.is_successful
    assert report.fights_checked == 14
    assert report.participants_checked == 56
    assert report.questions_checked == 70
    assert len(report.participant_total_mismatches) == 51
    assert not report.fight_structure_issues

    mismatch = report.participant_total_mismatches[0]
    assert mismatch.recorded_total != mismatch.computed_total
    with pytest.raises(Season2VerificationError):
        verifier.assert_valid()


def test_verifier_can_pass_after_normalising_totals(tmp_path: Path) -> None:
    store = _import_sample_tour(tmp_path, tour_number=1)

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        participant_ids = [row["id"] for row in conn.execute("SELECT id FROM fight_participants").fetchall()]
        for participant_id in participant_ids:
            computed_total = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) FROM question_results WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE fight_participants SET total_score = ? WHERE id = ?",
                (computed_total, participant_id),
            )
        conn.commit()

    verifier = Season2ResultsVerifier(store=store)
    report = verifier.verify()

    assert report.is_successful
    assert not report.participant_total_mismatches
    assert not report.fight_structure_issues
    assert verifier.assert_valid().is_successful


def test_verifier_flags_missing_question_results(tmp_path: Path) -> None:
    store = _import_sample_tour(tmp_path, tour_number=1)

    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "DELETE FROM question_results WHERE id IN (SELECT id FROM question_results LIMIT 1)"
        )
        conn.commit()

    verifier = Season2ResultsVerifier(store=store)
    report = verifier.verify()

    assert not report.is_successful
    assert report.fight_structure_issues
    issue = report.fight_structure_issues[0]
    assert issue.actual_results == issue.expected_results - 1
    assert issue.actual_questions == 5
