import json
from pathlib import Path

import pytest

from app import create_app


def _login(client):
    with client.session_transaction() as session:
        session["user_id"] = "tester"


@pytest.fixture(autouse=True)
def _clear_game_ten_env(monkeypatch):
    monkeypatch.delenv("GAME_TEN_ACTIVE_URL", raising=False)
    monkeypatch.delenv("GAME_TEN_ACTIVE_S3_BUCKET", raising=False)
    monkeypatch.delenv("GAME_TEN_ACTIVE_S3_KEY", raising=False)


def test_game_ten_active_template_fallback():
    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    payload = response.get_json()

    template_path = Path(__file__).resolve().parents[1] / "data" / "game_active.template.json"
    with template_path.open("r", encoding="utf-8") as handle:
        template_payload = json.load(handle)

    assert payload["question"]["title"] == template_payload["question"]["title"]
    assert len(payload.get("answers", [])) == len(template_payload.get("answers", []))


def test_game_ten_active_http_source(monkeypatch):
    expected_payload = {"question": {"title": "HTTP source"}, "answers": []}

    class _DummyResponse:
        status_code = 200
        ok = True

        def json(self):
            return expected_payload

    def _fake_get(url, timeout):
        assert url == "https://example.com/game_active.json"
        assert timeout == 10
        return _DummyResponse()

    monkeypatch.setenv("GAME_TEN_ACTIVE_URL", "https://example.com/game_active.json")
    monkeypatch.setattr("app.routes.requests.get", _fake_get)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload
