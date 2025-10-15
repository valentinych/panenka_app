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


def test_game_ten_active_s3_http_url_prefers_http(monkeypatch):
    expected_payload = {"question": {"title": "HTTP over S3"}, "answers": []}
    captured_urls = []

    def _fake_http(url, *, context_label):
        captured_urls.append((url, context_label))
        assert url == "https://my-bucket.s3.amazonaws.com/game_active.json"
        assert context_label == "game_active.json"
        return expected_payload

    def _fail_download(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("S3 download should not be invoked when HTTP succeeds")

    monkeypatch.setenv("GAME_TEN_ACTIVE_URL", "https://my-bucket.s3.amazonaws.com")
    monkeypatch.setattr("app.routes._load_json_from_http", _fake_http)
    monkeypatch.setattr("app.routes._download_json_from_s3", _fail_download)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload
    assert captured_urls == [
        ("https://my-bucket.s3.amazonaws.com/game_active.json", "game_active.json")
    ]


def test_game_ten_active_s3_url_without_key_uses_default(monkeypatch):
    expected_payload = {"question": {"title": "S3 source"}, "answers": []}
    captured_calls = []

    def _fake_download(bucket, key, *, context_label):
        captured_calls.append((bucket, key, context_label))
        return expected_payload

    def _fail_http(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setenv("GAME_TEN_ACTIVE_URL", "https://my-bucket.s3.amazonaws.com")
    monkeypatch.setattr("app.routes._load_json_from_http", _fail_http)
    monkeypatch.setattr("app.routes._download_json_from_s3", _fake_download)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload
    assert captured_calls == [("my-bucket", "game_active.json", "game_active.json")]


def test_game_ten_active_local_file(monkeypatch, tmp_path):
    expected_payload = {"question": {"title": "Local file"}, "answers": [1, 2, 3]}
    local_file = tmp_path / "game_active.json"
    local_file.write_text(json.dumps(expected_payload), encoding="utf-8")

    monkeypatch.setattr("app.routes.GAME_TEN_ACTIVE_LOCAL_PATH", local_file)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload
