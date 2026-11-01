import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

import main


class GroqTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.test_key = "unit-test-groq-key"
        self.client = MagicMock()
        self.client.__aenter__ = AsyncMock(return_value=self.client)
        self.client.__aexit__ = AsyncMock(return_value=None)
        self.post = AsyncMock()
        self.client.post = self.post
        self.client_factory = MagicMock(return_value=self.client)
        self.client_patch = patch(
            "main.httpx.AsyncClient",
            new=self.client_factory,
        )
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    def test_transcription_uses_configured_bearer_key(self):
        response = MagicMock()
        response.json.return_value = {"text": "Transcribed words."}
        self.post.return_value = response

        with patch.dict(os.environ, {"GROQ_API_KEY": self.test_key}):
            with TestClient(main.app) as test_client:
                result = test_client.post(
                    "/transcribe",
                    files={"file": ("sample.webm", b"audio bytes", "audio/webm")},
                )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"transcript": "Transcribed words."})
        request = self.post.await_args
        self.assertTrue(
            request.kwargs["headers"]["Authorization"]
            == f"Bearer {self.test_key}"
        )
        self.assertEqual(request.kwargs["files"]["file"][0], "recording.webm")
        self.assertEqual(request.kwargs["data"]["model"], "whisper-large-v3-turbo")
        self.client_factory.assert_called_once_with(timeout=30)

    def test_missing_key_returns_actionable_error_without_request(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with TestClient(main.app) as test_client:
                result = test_client.post(
                    "/transcribe",
                    files={"file": ("sample.webm", b"audio bytes", "audio/webm")},
                )

        self.assertEqual(result.status_code, 503)
        self.assertIn("GROQ_API_KEY", result.json()["detail"])
        self.assertFalse(self.test_key in result.text)
        self.post.assert_not_awaited()

    def test_auth_error_does_not_log_or_return_provider_response_body(self):
        request = httpx.Request(
            "POST",
            "https://api.groq.com/openai/v1/audio/transcriptions",
        )
        provider_response = httpx.Response(
            401,
            text=self.test_key,
            request=request,
        )
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "unauthorized",
            request=request,
            response=provider_response,
        )
        self.post.return_value = response

        with patch.dict(os.environ, {"GROQ_API_KEY": self.test_key}):
            with TestClient(main.app) as test_client:
                with self.assertLogs("main", level="ERROR") as captured:
                    result = test_client.post(
                        "/transcribe",
                        files={"file": ("sample.webm", b"audio bytes", "audio/webm")},
                    )

        self.assertEqual(result.status_code, 502)
        self.assertIn("GROQ_API_KEY", result.json()["detail"])
        self.assertFalse(self.test_key in result.text)
        self.assertFalse(self.test_key in "\n".join(captured.output))

    def test_timeout_returns_gateway_timeout_without_key_leak(self):
        self.post.side_effect = httpx.TimeoutException("provider timeout")

        with patch.dict(os.environ, {"GROQ_API_KEY": self.test_key}):
            with TestClient(main.app) as test_client:
                result = test_client.post(
                    "/transcribe",
                    files={"file": ("sample.webm", b"audio bytes", "audio/webm")},
                )

        self.assertEqual(result.status_code, 504)
        self.assertIn("timed out", result.json()["detail"])
        self.assertFalse(self.test_key in result.text)


if __name__ == "__main__":
    unittest.main()
