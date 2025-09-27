import unittest

from app.routes import DEFAULT_S3_KEY, _parse_s3_reference


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


if __name__ == "__main__":  # pragma: no cover - allows running file directly
    unittest.main()
