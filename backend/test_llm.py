import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from llm import (
    LLMProviderError,
    build_prompt,
    build_llm_request,
    get_provider_config,
    provider_catalog,
    query_llm,
)


class LLMProviderTests(unittest.TestCase):
    def test_groq_uses_smaller_evidence_budget(self):
        self.assertEqual(get_provider_config("groq")["max_chunks"], 8)
        self.assertEqual(get_provider_config("gemini")["max_chunks"], 15)

    def test_groq_request_uses_configured_model_and_compatible_stops(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            url, headers, payload = build_llm_request("hello", "groq")
            authorization_matches_key = (
                headers["Authorization"] == "Bearer " + os.environ["GROQ_API_KEY"]
            )

        self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertTrue(authorization_matches_key)
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_completion_tokens"], 900)
        self.assertNotIn("max_tokens", payload)
        self.assertLessEqual(len(payload["stop"]), 4)

    def test_gemini_request_uses_openai_compatible_endpoint(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            url, _, payload = build_llm_request("hello", "gemini")

        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertEqual(payload["reasoning_effort"], "low")

    def test_missing_key_is_actionable(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            LLMProviderError, "GEMINI_API_KEY"
        ):
            build_llm_request("hello", "gemini")

    def test_missing_groq_key_is_actionable_without_exposing_a_value(self):
        test_key = "unit-test-groq-key"
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with self.assertRaisesRegex(LLMProviderError, "GROQ_API_KEY") as raised:
                build_llm_request("hello", "groq")

        self.assertFalse(test_key in str(raised.exception))

    def test_provider_catalog_does_not_expose_keys(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "secret"}, clear=True):
            groq = next(item for item in provider_catalog() if item["id"] == "groq")

        self.assertTrue(groq["available"])
        self.assertNotIn("secret", str(groq))

    def test_workflow_prompt_requires_every_planned_step(self):
        steps = [
            "POST create customer",
            "POST attach payment method",
            "POST create subscription",
        ]
        chunks = [{
            "text": "Method: POST\nPath: /v1/customers",
            "metadata": {
                "method": "POST",
                "path": "/v1/customers",
                "retrieval_query": steps[0],
                "workflow_steps": steps,
            },
        }]

        prompt = build_prompt("create a subscribed customer", chunks)

        self.assertIn("3-step workflow", prompt)
        self.assertIn("Repeat through **Step 3**", prompt)
        self.assertIn(
            "Exact endpoint not found in retrieved spec sections.",
            prompt,
        )
        self.assertIn(
            "Never substitute a related endpoint for the requested operation.",
            prompt,
        )
        self.assertIn("3. POST create subscription", prompt)
        self.assertIn("[Evidence retrieved for: POST create customer]", prompt)

    def test_document_prompt_uses_document_citation_instead_of_endpoint(self):
        prompt = build_prompt(
            "How do I refresh a token?",
            [{
                "text": "Refresh tokens expire after one hour.",
                "metadata": {
                    "source_file": "auth-guide.pdf",
                    "document_type": "pdf",
                    "chunk_index": 0,
                },
            }],
        )

        self.assertIn("**Document:** `filename` (chunk N)", prompt)
        self.assertIn("[Document source: auth-guide.pdf (chunk 1)]", prompt)
        self.assertIn("Do not invent an API endpoint.", prompt)

    def test_pdf_document_prompt_contains_file_citation_and_content(self):
        prompt = build_prompt(
            "How does pagination work?",
            [{
                "text": "Use the next_cursor value to request the next page.",
                "metadata": {
                    "source_file": "pagination.pdf",
                    "document_type": "pdf",
                    "chunk_index": 2,
                },
            }],
        )

        self.assertIn("[Document source: pagination.pdf (chunk 3)]", prompt)
        self.assertIn("Use the next_cursor value", prompt)
        self.assertIn("**Document:** `filename` (chunk N)", prompt)

    def test_mixed_prompt_instructs_both_citation_formats(self):
        prompt = build_prompt(
            "How do I refresh a token and which API operation does that?",
            [
                {
                    "text": "POST /tokens/refresh",
                    "metadata": {
                        "method": "POST",
                        "path": "/tokens/refresh",
                        "summary": "Refresh token",
                    },
                },
                {
                    "text": "Refresh tokens expire after one hour.",
                    "metadata": {
                        "source_file": "auth-guide.txt",
                        "document_type": "txt",
                        "chunk_index": 0,
                    },
                },
            ],
        )

        self.assertIn("**Endpoint:** METHOD path", prompt)
        self.assertIn("**Document:** `filename` (chunk N)", prompt)
        self.assertIn("POST /tokens/refresh", prompt)
        self.assertIn("[Document source: auth-guide.txt (chunk 1)]", prompt)

    def test_endpoint_only_prompt_keeps_existing_format(self):
        prompt = build_prompt(
            "How do I refresh a token?",
            [{
                "text": "Refresh token - POST /tokens/refresh",
                "metadata": {
                    "method": "POST",
                    "path": "/tokens/refresh",
                    "summary": "Refresh token",
                },
            }],
        )

        self.assertIn("**Endpoint:** [HTTP METHOD] [path]", prompt)
        self.assertNotIn("[Document source:", prompt)

    def test_evidence_budget_compacts_large_schemas_without_dropping_steps(self):
        steps = ["POST create customer", "POST create subscription"]
        body = {
            "required_fields": [],
            "all_fields": {
                "customer": {
                    "type": "string",
                    "description": "The customer identifier used for the subscription.",
                },
                "items": {
                    "type": "array",
                    "description": "Prices and quantities for the subscription.",
                },
                "unrelated_configuration": {
                    "type": "object",
                    "description": "x" * 6000,
                },
            },
        }
        chunks = []
        for index, step in enumerate(steps):
            chunks.append({
                "text": (
                    f"Operation: POST /step-{index + 1}\nSummary: {step}\n"
                    f"Request Body Fields: {json.dumps(body)}\nResponses: 200"
                ),
                "metadata": {
                    "retrieval_query": step,
                    "workflow_steps": steps,
                },
            })

        prompt = build_prompt(
            "create a customer and subscription", chunks, max_evidence_chars=2400
        )

        self.assertIn("POST /step-1", prompt)
        self.assertIn("POST /step-2", prompt)
        self.assertIn("- customer (string, optional)", prompt)
        self.assertIn("- items (array, optional)", prompt)
        self.assertLess(len(prompt), 6000)


class GroqRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_missing_key_fails_before_network_request(self):
        client_factory = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch("llm.httpx.AsyncClient", new=client_factory):
                with self.assertRaisesRegex(LLMProviderError, "GROQ_API_KEY"):
                    await query_llm("hello", "groq")

        client_factory.assert_not_called()

    async def test_query_sends_configured_bearer_key_without_logging_it(self):
        test_key = "unit-test-groq-key"
        response = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": "A safe answer."}}],
        }
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)

        with patch.dict(os.environ, {"GROQ_API_KEY": test_key}):
            with patch("llm.httpx.AsyncClient", return_value=client):
                with self.assertLogs("llm", level="INFO") as captured:
                    answer = await query_llm("hello", "groq")

        request = client.post.await_args
        self.assertTrue(
            request.kwargs["headers"]["Authorization"] == f"Bearer {test_key}"
        )
        self.assertEqual(answer, "A safe answer.")
        self.assertFalse(test_key in "\n".join(captured.output))

    async def test_query_timeout_returns_safe_error(self):
        test_key = "unit-test-groq-key"
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch.dict(os.environ, {"GROQ_API_KEY": test_key}):
            with patch("llm.httpx.AsyncClient", return_value=client):
                with self.assertLogs("llm", level="ERROR") as captured:
                    with self.assertRaisesRegex(LLMProviderError, "timed out") as raised:
                        await query_llm("hello", "groq")

        self.assertFalse(test_key in str(raised.exception))
        self.assertFalse(test_key in "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
