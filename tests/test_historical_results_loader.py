import time

from app.historical_results_loader import load_historical_dataset
from app.season2 import Season2ResultsStore


def test_future_season_fixtures_are_loaded():
    load_historical_dataset.cache_clear()
    dataset = load_historical_dataset()

    assert 3 in dataset["seasons"]
    assert 4 in dataset["seasons"]

    fight_seasons = {fight.get("season_number") for fight in dataset["fights"]}
    assert {3, 4}.issubset(fight_seasons)


def test_dataset_uses_database_when_available(tmp_path, monkeypatch):
    load_historical_dataset.cache_clear()

    db_path = tmp_path / "results.sqlite3"
    store = Season2ResultsStore(db_path=str(db_path), enable_season_seed=False)

    with store.connection() as conn:
        for season_number in range(1, 5):
            season_slug = f"{season_number:02d}"
            season_row = conn.execute(
                "SELECT id FROM seasons WHERE season_number = ?", (season_number,)
            ).fetchone()
            if season_row is None:
                cursor = conn.execute(
                    "INSERT INTO seasons (season_number, slug) VALUES (?, ?)",
                    (season_number, season_slug),
                )
                season_id = int(cursor.lastrowid)
            else:
                season_id = int(season_row["id"])

            tour_cursor = conn.execute(
                "INSERT INTO tours (season_id, tour_number, gid) VALUES (?, ?, ?)",
                (season_id, 1, None),
            )
            tour_id = int(tour_cursor.lastrowid)

            fight_code = f"S{season_number:02d}E01F01"
            fight_cursor = conn.execute(
                (
                    "INSERT INTO fights (tour_id, fight_number, ordinal, fight_code, letter, "
                    "imported_at, source_path, import_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (tour_id, 1, 1, fight_code, "A", time.time(), None, None),
            )
            fight_id = int(fight_cursor.lastrowid)

            player_name = f"Season {season_number} DB Player"
            conn.execute(
                (
                    "INSERT INTO fight_participants (fight_id, display_name, normalized_name, "
                    "seat_index, total_score) VALUES (?, ?, ?, ?, ?)"
                ),
                (fight_id, player_name, player_name.lower(), 1, 100 - season_number),
            )

        conn.commit()

    monkeypatch.setenv("PANENKA_RESULTS_DB", str(db_path))

    try:
        dataset = load_historical_dataset()
    finally:
        load_historical_dataset.cache_clear()
        monkeypatch.delenv("PANENKA_RESULTS_DB", raising=False)

    fight_codes = {fight.get("fight_code") for fight in dataset["fights"]}
    assert fight_codes == {
        "S01E01F01",
        "S02E01F01",
        "S03E01F01",
        "S04E01F01",
    }

    player_names = {
        participant.get("display")
        for fight in dataset["fights"]
        for participant in fight.get("participants", [])
    }
    assert "Season 3 DB Player" in player_names
    assert "Season 4 DB Player" in player_names
