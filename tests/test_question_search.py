from app.question_store import QuestionStore


def _sample_question(text: str) -> tuple:
    return (
        1,  # season_number
        1,  # row_number
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


def test_sample_questions_seeded(tmp_path):
    db_path = tmp_path / "seeded.sqlite3"
    store = QuestionStore(str(db_path))

    results = store.search_questions(limit=5)

    assert results, "Expected bundled sample questions to be available by default"
    combined_text = " ".join(row["question_text"].lower() for row in results if row["question_text"])
    assert "радебе" in combined_text
