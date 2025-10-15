import json
from pathlib import Path

import pytest

from app import create_app


def _login(client):
    with client.session_transaction() as session:
        session["user_id"] = "888"


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

    assert payload["questions"][0]["title"] == template_payload["questions"][0]["title"]
    assert len(payload.get("questions", [])) == len(template_payload.get("questions", []))


def test_game_ten_active_http_source(monkeypatch):
    expected_payload = {"questions": [{"title": "HTTP source"}]}

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
    expected_payload = {"questions": [{"title": "HTTP over S3"}]}
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
    expected_payload = {"questions": [{"title": "S3 source"}]}
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
    expected_payload = {"questions": [{"title": "Local file", "answers": [1, 2, 3]}]}
    local_file = tmp_path / "game_active.json"
    local_file.write_text(json.dumps(expected_payload), encoding="utf-8")

    monkeypatch.setattr("app.routes.GAME_TEN_ACTIVE_LOCAL_PATH", local_file)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload


def test_game_ten_active_uses_auth_bucket(monkeypatch):
    expected_payload = {"questions": [{"title": "Auth bucket"}]}
    captured_calls = []

    def _fake_download(bucket, key, *, context_label):
        captured_calls.append((bucket, key, context_label))
        return expected_payload

    monkeypatch.setenv("AUTH_JSON_S3_BUCKET", "secure-bucket")
    monkeypatch.setenv("AUTH_JSON_S3_KEY", "private/auth.json")
    monkeypatch.setattr("app.routes._download_json_from_s3", _fake_download)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload
    assert captured_calls == [
        ("secure-bucket", "private/game_active.json", "game_active.json")
    ]


def test_game_ten_active_uses_auth_uri(monkeypatch):
    expected_payload = {"questions": [{"title": "Auth URI"}]}
    captured_calls = []

    def _fake_download(bucket, key, *, context_label):
        captured_calls.append((bucket, key, context_label))
        return expected_payload

    monkeypatch.setenv(
        "AUTH_JSON_S3_URI", "s3://another-bucket/nested/deeper/auth.json"
    )
    monkeypatch.setattr("app.routes._download_json_from_s3", _fake_download)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/active")

    assert response.status_code == 200
    assert response.get_json() == expected_payload
    assert captured_calls == [
        ("another-bucket", "nested/deeper/game_active.json", "game_active.json")
    ]


def test_game_ten_run_missing_returns_404(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.routes.GAME_TEN_RUN_LOCAL_PATH", tmp_path / "game_run.json"
    )

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/run")

    assert response.status_code == 404


def test_game_ten_run_put_uses_s3(monkeypatch):
    captured = []

    def _fake_upload(bucket, key, payload, *, context_label):
        captured.append((bucket, key, context_label, payload))

    monkeypatch.setenv("GAME_TEN_ACTIVE_URL", "s3://my-bucket/path/game_active.json")
    monkeypatch.setattr("app.routes._upload_json_to_s3", _fake_upload)

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.put("/api/game-ten/run", json={"foo": "bar"})

    assert response.status_code == 200
    assert captured == [
        ("my-bucket", "path/game_run.json", "game_run.json", {"foo": "bar"})
    ]


def test_game_ten_run_get_reads_s3(monkeypatch):
    expected_payload = {"state": "ok"}

    def _fake_download(bucket, key, *, context_label):
        assert bucket == "bucket"
        assert key == "folder/game_run.json"
        assert context_label == "game_run.json"
        return expected_payload

    monkeypatch.setenv("GAME_TEN_ACTIVE_URL", "s3://bucket/folder/game_active.json")
    monkeypatch.setattr(
        "app.routes._download_json_from_s3_optional", _fake_download
    )

    app = create_app()
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/game-ten/run")

    assert response.status_code == 200
    assert response.get_json() == expected_payload


def test_game_ten_route_forbidden_for_non_admin():
    app = create_app()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "123"
        response = client.get("/game-ten")

    assert response.status_code == 403
