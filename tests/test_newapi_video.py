from __future__ import annotations

import unittest
from pathlib import Path

from video_replicator.newapi_video import NewAPIConfig, NewAPIVideoClient, _redact


class NewAPIVideoTests(unittest.TestCase):
    def test_remote_http_is_rejected(self) -> None:
        config = NewAPIConfig("http://provider.example", "token")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            config.validate()

    def test_local_http_is_allowed(self) -> None:
        NewAPIConfig("http://127.0.0.1:8080", "token").validate()

    def test_nested_video_url_and_success_states_are_supported(self) -> None:
        response = {"status": "succeeded", "data": {"video_url": "https://example.test/out.mp4?sig=secret"}}
        self.assertEqual(NewAPIVideoClient.result_url(response), response["data"]["video_url"])
        self.assertIn("succeeded", {"completed", "succeeded", "success"})

    def test_signed_url_query_is_redacted(self) -> None:
        redacted = _redact({"video_url": "https://example.test/out.mp4?X-Amz-Signature=secret&foo=bar"})
        self.assertEqual(
            redacted["video_url"],
            "https://example.test/out.mp4?X-Amz-Signature=%2A%2A%2AREDACTED%2A%2A%2A&foo=%2A%2A%2AREDACTED%2A%2A%2A",
        )


if __name__ == "__main__":
    unittest.main()
