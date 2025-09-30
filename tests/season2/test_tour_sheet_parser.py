from pathlib import Path

import pytest

from app.season2 import Season2TourSheet
from app.season2.tour_sheet_parser import _normalise_int

DATA_ROOT = Path("data/raw/season02/csv")


def _load_tour(number: int) -> Season2TourSheet:
    path = DATA_ROOT / f"{number + 11:02d}_tour{number}.csv"
    if not path.exists():
        pytest.skip(f"Tour {number} CSV snapshot not available: {path}")
    return Season2TourSheet.from_csv(path, tour_number=number)


def _synthetic_sheet() -> Season2TourSheet:
    rows = [
        ["1", "", "", "", "1", "", "", "", "Ведущие тура"],
        ["", "", "", "", "", "", "", "", ""],
        ["", " 200", "−30", "", "", " 150", "−20", "", ""],
        ["10", "5", "", "", "10", "7", "-7", "", ""],
        ["20", "", "\xa0", "", "20", "", "-5", "", ""],
        ["30", "-15", "", "", "30", " 3", "", "", ""],
        ["40", "", "", "", "40", "", "2", "", ""],
        ["50", "0", "", "", "50", "-2", "", "", ""],
    ]
    return Season2TourSheet(tour_number=99, rows=rows)


def test_fight_count_in_tour1():
    sheet = _load_tour(1)
    fights = list(sheet.iter_fights())
    assert len(fights) == 14


def test_fight_three_totals_and_deltas():
    sheet = _load_tour(1)
    fights = list(sheet.iter_fights())
    fight = fights[2]  # zero-based index → third fight

    assert fight.ordinal == 3
    assert fight.player_totals == [310, 170, -120, 20]

    assert [q.nominal for q in fight.questions] == [10, 20, 30, 40, 50]
    assert fight.questions[0].deltas == [10, 0, 0, 0]
    assert fight.questions[-1].deltas == [50, 0, 0, 0]


def test_fight_one_handles_zero_totals():
    sheet = _load_tour(1)
    first_fight = next(sheet.iter_fights())

    assert first_fight.player_totals == [50, 140, 20, 0]
    first_question = first_fight.questions[0]
    assert first_question.nominal == 10
    assert first_question.deltas == [0, 0, 10, 0]


def test_normalise_int_handles_unicode_tokens():
    assert _normalise_int("") == 0
    assert _normalise_int("\xa0") == 0
    assert _normalise_int(" −30 ") == -30
    assert _normalise_int("12,0") == 12


def test_iter_fights_on_synthetic_sheet():
    sheet = _synthetic_sheet()
    fights = list(sheet.iter_fights())

    assert len(fights) == 2
    assert fights[0].start_column == 0
    assert fights[1].start_column == 4

    first, second = fights

    assert first.player_totals == [200, -30]
    assert [q.nominal for q in first.questions] == [10, 20, 30, 40, 50]
    assert first.questions[1].deltas == [0, 0]
    assert first.questions[2].deltas == [-15, 0]

    assert second.player_totals == [150, -20]
    assert second.questions[0].deltas == [7, -7]
    assert second.questions[1].deltas == [0, -5]
    assert second.questions[2].deltas == [3, 0]
    assert second.questions[-1].deltas == [-2, 0]


def test_sample_fights_snapshot():
    sheet = _load_tour(1)
    sample = {
        fight.ordinal: {
            "player_totals": fight.player_totals,
            "questions": [
                {"nominal": row.nominal, "deltas": row.deltas}
                for row in fight.questions
            ],
        }
        for fight in sheet.iter_fights()
        if fight.ordinal in {1, 3, 7, 14}
    }

    assert sample == {
        1: {
            "player_totals": [50, 140, 20, 0],
            "questions": [
                {"nominal": 10, "deltas": [0, 0, 10, 0]},
                {"nominal": 20, "deltas": [0, 0, 0, 0]},
                {"nominal": 30, "deltas": [0, 0, 0, 0]},
                {"nominal": 40, "deltas": [0, 0, 0, 0]},
                {"nominal": 50, "deltas": [0, 50, 0, 0]},
            ],
        },
        3: {
            "player_totals": [310, 170, -120, 20],
            "questions": [
                {"nominal": 10, "deltas": [10, 0, 0, 0]},
                {"nominal": 20, "deltas": [20, 0, 0, 0]},
                {"nominal": 30, "deltas": [30, 0, 0, 0]},
                {"nominal": 40, "deltas": [0, 40, 0, 0]},
                {"nominal": 50, "deltas": [50, 0, 0, 0]},
            ],
        },
        7: {
            "player_totals": [-60, 250, 50, 170],
            "questions": [
                {"nominal": 10, "deltas": [0, 0, 0, 10]},
                {"nominal": 20, "deltas": [-20, 20, 0, 0]},
                {"nominal": 30, "deltas": [0, 30, 0, 0]},
                {"nominal": 40, "deltas": [0, 0, 0, 0]},
                {"nominal": 50, "deltas": [0, -50, 0, 50]},
            ],
        },
        14: {
            "player_totals": [130, 240, 10, 0],
            "questions": [
                {"nominal": 10, "deltas": [0, 0, 0, 0]},
                {"nominal": 20, "deltas": [0, 20, 0, 0]},
                {"nominal": 30, "deltas": [0, 30, 0, 0]},
                {"nominal": 40, "deltas": [0, 0, 0, 0]},
                {"nominal": 50, "deltas": [0, 0, 0, 0]},
            ],
        },
    }
