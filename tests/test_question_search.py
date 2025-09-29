from app.question_store import QuestionStore


from typing import Optional


def _sample_question(
    text: str,
    *,
    season: int = 1,
    row_number: int = 1,
    value: int = 10,
    author: Optional[str] = None,
    editor: Optional[str] = None,
    topic: Optional[str] = None,
    taken_count: Optional[int] = None,
    not_taken_count: Optional[int] = None,
    comment: Optional[str] = None,
) -> tuple:
    return (
        season,  # season_number
        row_number,  # row_number
        None,  # played_at_raw
        None,  # played_at
        editor,  # editor
        topic,  # topic
        value,  # question_value
        author,  # author
        text,  # question_text
        "Лидс Юнайтед",  # answer_text
        taken_count,  # taken_count
        not_taken_count,  # not_taken_count
        comment,  # comment
    )


def test_search_matches_any_keyword(tmp_path):
    db_path = tmp_path / "questions.sqlite3"
    store = QuestionStore(str(db_path))
    store.replace_all([
        _sample_question("Лукас Радебе является воспитанником южноафриканского клуба."),
    ])

    results = store.search_questions(["радебе", "музыка", "культура"], limit=10)

    assert results, "Expected at least one match when any keyword is present"
    assert any("радебе" in row["question_text"].lower() for row in results)


def test_sample_questions_seeded_by_default(tmp_path):
    db_path = tmp_path / "seeded.sqlite3"
    store = QuestionStore(str(db_path))

    results = store.search_questions(limit=5)

    assert results, "Expected bundled sample questions to be available by default"
    combined_text = " ".join(
        row["question_text"].lower() for row in results if row["question_text"]
    )
    assert "паненка" in combined_text


def test_sample_questions_can_be_disabled(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    store = QuestionStore(str(db_path), enable_sample_data=False)

    results = store.search_questions(limit=5)

    assert results == []


def test_list_questions_and_stats(tmp_path):
    db_path = tmp_path / "list.sqlite3"
    store = QuestionStore(str(db_path))
    store.replace_all(
        [
            _sample_question("Вопрос A", row_number=1),
            _sample_question("Вопрос B", row_number=2),
            _sample_question("Вопрос C", row_number=3),
        ]
    )

    rows = store.list_questions(limit=2, offset=1)
    assert [row["row_number"] for row in rows] == [2, 3]

    stats = store.get_question_stats()
    assert stats["total"] == 3
    assert stats["last_imported_at"] is not None

    seasons = store.list_seasons()
    assert seasons == [1]


def test_search_applies_structured_filters(tmp_path):
    db_path = tmp_path / "filters.sqlite3"
    store = QuestionStore(str(db_path))
    store.replace_all(
        [
            _sample_question(
                "Вопрос без фильтра",
                season=1,
                row_number=1,
                value=50,
                author="Автор А",
                editor="Редактор А",
            ),
            _sample_question(
                "Фильтрация по параметрам",
                season=2,
                row_number=2,
                value=100,
                author="Автор Б",
                editor="Редактор Б",
                taken_count=3,
                not_taken_count=1,
                comment="Комментарий",
            ),
        ]
    )

    results = store.search_questions(
        limit=10,
        season_number=2,
        question_value=100,
        author="Автор Б",
        editor="Редактор Б",
    )

    assert len(results) == 1
    row = results[0]
    assert row["season_number"] == 2
    assert row["question_value"] == 100
    assert row["author"] == "Автор Б"
    assert row["editor"] == "Редактор Б"
    assert row["taken_count"] == 3
    assert row["not_taken_count"] == 1
    assert row["comment"] == "Комментарий"
