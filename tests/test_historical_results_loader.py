from app.historical_results_loader import load_historical_dataset


def test_future_season_fixtures_are_loaded():
    dataset = load_historical_dataset()

    assert 3 in dataset["seasons"]
    assert 4 in dataset["seasons"]

    fight_seasons = {fight.get("season_number") for fight in dataset["fights"]}
    assert {3, 4}.issubset(fight_seasons)
