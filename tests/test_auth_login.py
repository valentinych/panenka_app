import json
import os
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
import http.cookiejar

from app.routes import (
    AUTH_ENV_VAR,
    AUTH_FILE,
    AUTH_JSON_URL_ENV,
    AUTH_S3_BUCKET_ENV,
    AUTH_S3_BUCKET_FALLBACK_ENV,
    AUTH_S3_KEY_ENV,
    AUTH_S3_URI_ENV,
    load_credentials,
)


class AuthJsonLoginTestCase(unittest.TestCase):
    """Integration test that verifies auth.json credentials and remote login."""

    LOGIN_CODE = "888"
    PASSWORD_CODE = "6969"
    AUTH_FIXTURE = {
        "users": [
            {
                "login": LOGIN_CODE,
                "password": PASSWORD_CODE,
                "name": "Integration Test Player",
            }
        ]
    }

    ENV_VARS = [
        AUTH_ENV_VAR,
        AUTH_S3_BUCKET_ENV,
        AUTH_S3_BUCKET_FALLBACK_ENV,
        AUTH_S3_KEY_ENV,
        AUTH_S3_URI_ENV,
        AUTH_JSON_URL_ENV,
    ]

    REMOTE_LOGIN_URL = "https://panenka-live-ae2234475edc.herokuapp.com/"
    REMOTE_DASHBOARD_PATH = "/dashboard"

    def setUp(self):
        self._env_backup = {}
        for name in self.ENV_VARS:
            if name in os.environ:
                self._env_backup[name] = os.environ[name]
                del os.environ[name]

        self._auth_backup = None
        if AUTH_FILE.exists():
            self._auth_backup = AUTH_FILE.read_text(encoding="utf-8")

        AUTH_FILE.write_text(json.dumps(self.AUTH_FIXTURE), encoding="utf-8")

    def tearDown(self):
        if self._auth_backup is None:
            try:
                AUTH_FILE.unlink()
            except FileNotFoundError:
                pass
        else:
            AUTH_FILE.write_text(self._auth_backup, encoding="utf-8")

        for name, value in self._env_backup.items():
            os.environ[name] = value

    def test_auth_json_allows_login_to_remote_app(self):
        credentials = load_credentials()
        self.assertIn(self.LOGIN_CODE, credentials)
        self.assertEqual(credentials[self.LOGIN_CODE]["password"], self.PASSWORD_CODE)

        opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        post_data = urlencode({"login": self.LOGIN_CODE, "password": self.PASSWORD_CODE}).encode()
        request = Request(self.REMOTE_LOGIN_URL, data=post_data, method="POST")

        try:
            with opener.open(request, timeout=15) as response:
                final_url = response.geturl()
                body = response.read().decode("utf-8", errors="ignore")
        except (URLError, HTTPError) as exc:
            self.skipTest(f"Unable to reach remote login endpoint: {exc}")
            return

        self.assertIn(self.REMOTE_DASHBOARD_PATH, final_url)
        self.assertIn(self.LOGIN_CODE, body)
        self.assertIn("Logout", body)

    def test_numeric_credentials_are_coerced_to_strings(self):
        numeric_payload = {
            "users": [
                {
                    "login": 123,
                    "password": 4567,
                    "name": "Numeric Player",
                }
            ]
        }

        os.environ[AUTH_ENV_VAR] = json.dumps(numeric_payload)
        try:
            credentials = load_credentials()
        finally:
            del os.environ[AUTH_ENV_VAR]

        self.assertIn("123", credentials)
        self.assertEqual(credentials["123"]["password"], "4567")
        self.assertEqual(credentials["123"]["name"], "Numeric Player")


if __name__ == "__main__":  # pragma: no cover - allows running file directly
    unittest.main()
