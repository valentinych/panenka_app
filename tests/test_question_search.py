from app.question_store import QuestionStore


def _sample_question(text: str, *, season: int = 1, row_number: int = 1) -> tuple:
    return (
        season,  # season_number
        row_number,  # row_number
        None,  # played_at_raw
        None,  # played_at
        None,  # editor
        None,  # topic
        10,  # question_value
        None,  # author
        text,  # question_text
        "Лидс Юнайтед",  # answer_text
        None,  # taken_count
        None,  # not_taken_count
        None,  # comment
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
