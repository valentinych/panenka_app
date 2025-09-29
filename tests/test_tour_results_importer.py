import json
from pathlib import Path


def _load_fixture() -> dict:
    fixture_path = Path("app/static/data/season01_tour_results.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return payload


def _find_fight(payload: dict, code: str) -> dict:
    for tour in payload["tours"]:
        for fight in tour["fights"]:
            if fight["code"] == code:
                return fight
    raise AssertionError(f"Fight {code} not found in payload")


def test_first_fight_structure():
    payload = _load_fixture()
    fight = _find_fight(payload, "S01E02F01")

    assert fight["letter"] == "A"
    assert [player["name"] for player in fight["players"]] == [
        "Александр Ефименко",
        "Мария Тимохова",
        "Денис Лавренюк",
        "Евгений Капитульский",
    ]
    assert [player["total"] for player in fight["players"]] == [400, 40, 300, 180]

    first_question = fight["questions"][0]
    assert first_question["theme"] == "Цветная"
    assert first_question["nominal"] == 10
    assert [result["delta"] for result in first_question["results"]] == [10, 0, 0, 0]
    assert [result["is_correct"] for result in first_question["results"]] == [
        True,
        False,
        False,
        False,
    ]
    assert len(fight["questions"]) == 50


def test_tour_fallback_letters_present():
    payload = _load_fixture()
    fight = _find_fight(payload, "S01E08F01")
    # The source sheet omits "Бой <letter>" headers for tour 8, ensure we still
    # derive sequential letters.
    assert fight["letter"] == "A"


def test_all_expected_tours_present():
    payload = _load_fixture()
    tour_numbers = {tour["tour_number"] for tour in payload["tours"]}
    assert tour_numbers == set(range(2, 12))
