from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.tour_statistics_importer import TourStatisticsImporter, _normalise_text
from app.tour_statistics_store import TourStatisticsStore


SHEET_ROWS = [
    [
        "S01E02F01",
        "",
        "",
        "",
        "",
        "",
        "",
        "S01E02F02",
        "",
        "",
        "",
        "",
        "",
        "",
    ],
    [
        "Темы",
        "Александр Ефименко",
        "Мария Тимохова",
        "Денис Лавренюк",
        "Евгений Капитульский",
        "Номинал",
        "",
        "Темы",
        "Иван Иванов",
        "Пётр Петров",
        "Сидор Сидоров",
        "Анна Аннова",
        "Номинал",
        "",
    ],
    [
        "",
        "70",
        "-10",
        "40",
        "0",
        "",
        "",
        "",
        "100",
        "50",
        "-20",
        "-30",
        "",
        "",
    ],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    [
        "Цветная",
        "10",
        "0",
        "-10",
        "0",
        "10",
        "",
        "Тема А",
        "30",
        "10",
        "-10",
        "-20",
        "10",
        "",
    ],
    [
        "Бартез",
        "20",
        "0",
        "20",
        "-20",
        "20",
        "",
        "Тема Б",
        "20",
        "10",
        "-5",
        "5",
        "20",
        "",
    ],
    [
        "Блан",
        "40",
        "-10",
        "20",
        "-10",
        "30",
        "",
        "Тема В",
        "30",
        "10",
        "-5",
        "-5",
        "30",
        "",
    ],
    [
        "Далма",
        "0",
        "0",
        "10",
        "-10",
        "40",
        "",
        "Тема Г",
        "10",
        "10",
        "0",
        "-5",
        "40",
        "",
    ],
    [
        "Зидан",
        "0",
        "0",
        "0",
        "40",
        "50",
        "",
        "Тема Д",
        "10",
        "10",
        "0",
        "-5",
        "50",
        "",
    ],
]


PLAYERS = [
    "Александр Ефименко",
    "Мария Тимохова",
    "Денис Лавренюк",
    "Евгений Капитульский",
    "Иван Иванов",
    "Пётр Петров",
    "Сидор Сидоров",
    "Анна Аннова",
]


THEMES = [
    "Цветная",
    "Бартез",
    "Блан",
    "Далма",
    "Зидан",
    "Тема А",
    "Тема Б",
    "Тема В",
    "Тема Г",
    "Тема Д",
]


@pytest.fixture
def store(tmp_path: Path) -> TourStatisticsStore:
    db_path = tmp_path / "tour_stats.sqlite3"
    store = TourStatisticsStore(db_path=str(db_path))
    store.ensure_schema()
    with store.connection() as conn:
        for player in PLAYERS:
            normalized = _normalise_text(player)
            player_id = conn.execute(
                "INSERT INTO players (full_name, normalized_name) VALUES (?, ?)",
                (player, normalized),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO player_aliases (player_id, alias, normalized_alias)
                VALUES (?, ?, ?)
                """,
                (player_id, player, normalized),
            )
        for theme in THEMES:
            conn.execute(
                "INSERT INTO themes (title) VALUES (?)",
                (theme,),
            )
        conn.commit()
    return store


def test_imports_two_fights_and_results(store: TourStatisticsStore) -> None:
    importer = TourStatisticsImporter(store=store, sheet_id="sheet", sheet_name="S01E02")

    summary = importer.import_rows(SHEET_ROWS)

    assert summary.fights_imported == 2
    assert summary.participants_inserted == 8
    assert summary.questions_inserted == 10
    assert summary.question_results_inserted == 40

    with store.connection() as conn:
        fights = conn.execute(
            """
            SELECT id, fight_code, sheet_column_range, question_row_start, question_row_end
            FROM fights
            ORDER BY fight_code
            """
        ).fetchall()

        assert [row["fight_code"] for row in fights] == ["S01E02F01", "S01E02F02"]
        assert fights[0]["sheet_column_range"] == "A:F"
        assert fights[0]["question_row_start"] == 5
        assert fights[0]["question_row_end"] == 9
        assert fights[1]["sheet_column_range"] == "H:M"

        participants = conn.execute(
            """
            SELECT seat_index, total_score, player_id
            FROM fight_participants
            WHERE fight_id = ?
            ORDER BY seat_index
            """,
            (fights[0]["id"],),
        ).fetchall()
        first_fight_player_ids = [row["player_id"] for row in participants]
        assert len(first_fight_player_ids) == 4

        question = conn.execute(
            """
            SELECT id, question_order, nominal, sheet_row
            FROM questions
            WHERE fight_id = ?
            ORDER BY question_order
            LIMIT 1
            """,
            (fights[0]["id"],),
        ).fetchone()
        assert question["nominal"] == 10
        assert question["sheet_row"] == 5

        results = conn.execute(
            """
            SELECT delta, is_correct
            FROM question_results
            WHERE question_id = ?
            ORDER BY participant_id
            """,
            (question["id"],),
        ).fetchall()
        assert [row["delta"] for row in results] == [10, 0, -10, 0]
        assert [row["is_correct"] for row in results] == [1, 0, 0, 0]


def test_imports_players_with_quoted_names(store: TourStatisticsStore) -> None:
    importer = TourStatisticsImporter(store=store, sheet_id="sheet", sheet_name="S01E02")

    quoted_rows = deepcopy(SHEET_ROWS)
    quoted_rows[1] = list(quoted_rows[1])
    quoted_rows[1][3] = ' " Денис Лавренюк" '

    importer.import_rows(quoted_rows)

    with store.connection() as conn:
        row = conn.execute(
            """
            SELECT p.full_name
            FROM fights f
            JOIN fight_participants fp ON fp.fight_id = f.id
            JOIN players p ON p.id = fp.player_id
            WHERE f.fight_code = ? AND fp.seat_index = ?
            """,
            ("S01E02F01", 3),
        ).fetchone()

    assert row is not None
    assert row["full_name"] == "Денис Лавренюк"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('" Денис Лавренюк"', "денис лавренюк"),
        ("«Мария Тимохова»", "мария тимохова"),
        ("“Евгений”   Капитульский", "евгений капитульский"),
    ],
)
def test_normalise_text_strips_quotes(raw: str, expected: str) -> None:
    assert _normalise_text(raw) == expected


def test_reimport_supersedes_previous_import(store: TourStatisticsStore) -> None:
    importer = TourStatisticsImporter(store=store, sheet_id="sheet", sheet_name="S01E02")

    importer.import_rows(SHEET_ROWS)
    importer.import_rows(SHEET_ROWS)

    with store.connection() as conn:
        statuses = conn.execute(
            "SELECT status FROM imports ORDER BY id",
        ).fetchall()

    assert [row["status"] for row in statuses] == ["superseded", "success"]


