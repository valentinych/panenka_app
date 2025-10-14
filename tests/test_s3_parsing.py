import json
import unittest

from unittest import mock

from app.routes import DEFAULT_S3_KEY, _load_from_url, _parse_s3_reference


class ParseS3ReferenceTestCase(unittest.TestCase):
    def test_supported_formats(self):
        cases = [
            ("s3://my-bucket/auth.json", "my-bucket", "auth.json"),
            ("s3://my-bucket", "my-bucket", DEFAULT_S3_KEY),
            (
                "https://player-creds.s3.amazonaws.com/auth.json",
                "player-creds",
                "auth.json",
            ),
            (
                "https://player-creds.s3.us-west-2.amazonaws.com/folder/auth.json",
                "player-creds",
                "folder/auth.json",
            ),
            (
                "https://player-creds.s3.dualstack.us-east-1.amazonaws.com/auth.json",
                "player-creds",
                "auth.json",
            ),
            (
                "https://s3.us-east-1.amazonaws.com/player-creds/auth.json",
                "player-creds",
                "auth.json",
            ),
            (
                "https://s3-accelerate.amazonaws.com/player-creds/auth.json",
                "player-creds",
                "auth.json",
            ),
            (
                "https://s3.dualstack.us-east-1.amazonaws.com/player-creds/auth.json",
                "player-creds",
                "auth.json",
            ),
            ("https://s3.amazonaws.com/player-creds", "player-creds", DEFAULT_S3_KEY),
            (
                "https://player-creds.s3-website-us-west-2.amazonaws.com/auth.json",
                "player-creds",
                "auth.json",
            ),
        ]

        for reference, expected_bucket, expected_key in cases:
            with self.subTest(reference=reference):
                bucket, key = _parse_s3_reference(reference)
                self.assertEqual(bucket, expected_bucket)
                self.assertEqual(key, expected_key)

    def test_invalid_or_missing_references(self):
        for reference in ("https://example.com/auth.json", None, ""):
            with self.subTest(reference=reference):
                bucket, key = _parse_s3_reference(reference)
                self.assertIsNone(bucket)
                self.assertIsNone(key)


class LoadFromUrlTestCase(unittest.TestCase):
    def _fake_urlopen(self, requested_urls):
        def fake_urlopen(url):
            requested_urls.append(url)

            class _Response:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return json.dumps({"status": "ok"}).encode("utf-8")

            return _Response()

        return fake_urlopen

    def test_appends_default_key_for_virtual_host_root(self):
        requested_urls = []
        with mock.patch(
            "urllib.request.urlopen", side_effect=self._fake_urlopen(requested_urls)
        ):
            payload = _load_from_url("https://player-creds.s3.amazonaws.com")

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(
            requested_urls[0].endswith(f"/{DEFAULT_S3_KEY}"),
            requested_urls[0],
        )

    def test_appends_default_key_for_path_style_root(self):
        requested_urls = []
        with mock.patch(
            "urllib.request.urlopen", side_effect=self._fake_urlopen(requested_urls)
        ):
            payload = _load_from_url("https://s3.amazonaws.com/player-creds")

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(
            requested_urls[0].endswith(f"/player-creds/{DEFAULT_S3_KEY}"),
            requested_urls[0],
        )

    def test_preserves_explicit_object_key(self):
        requested_urls = []
        with mock.patch(
            "urllib.request.urlopen", side_effect=self._fake_urlopen(requested_urls)
        ):
            payload = _load_from_url(
                "https://player-creds.s3.amazonaws.com/custom.json"
            )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(
            requested_urls[0].endswith("/custom.json"),
            requested_urls[0],
        )


if __name__ == "__main__":  # pragma: no cover - allows running file directly
    unittest.main()
