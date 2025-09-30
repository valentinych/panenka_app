from pathlib import Path

from app.season2.roster_parser import parse_clashes_rosters

FIXTURE_PATH = Path("tests/season2/fixtures/clashes_sample.csv")


def test_parse_clashes_rosters_extracts_players_per_fight():
    rosters = parse_clashes_rosters(FIXTURE_PATH)

    assert rosters[(1, 8)] == [
        "Артем Наумов",
        "Алексей Индоиту",
        "Александр Черкасов",
        "Павел Трощенко",
    ]
    assert rosters[(1, 12)] == [
        "Егор Куликов",
        "Руслан Огородник",
        "Мария Тимохова",
        "Хорхе Чаос",
    ]
    assert rosters[(2, 3)] == [
        "Михаил Басс",
        "Сергей Рева",
        "Абдугани Сафи",
        "Хорхе Чаос",
    ]


def test_parse_clashes_rosters_handles_missing_file(tmp_path):
    missing = tmp_path / "missing.csv"
    assert parse_clashes_rosters(missing) == {}
