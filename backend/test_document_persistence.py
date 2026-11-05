import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import vectorStore
from fastapi.testclient import TestClient
import main


class DocumentIsolationAndPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_index_dir = vectorStore.BM25
        self.original_legacy_dirs = vectorStore.LEGACY_BM25_DIRS
        self.index_dir = Path(self.temporary_directory.name) / "indexes"
        self.index_dir.mkdir()
        vectorStore.BM25 = self.index_dir
        vectorStore.LEGACY_BM25_DIRS = ()

        self.client = TestClient(main.app)

    def tearDown(self):
        vectorStore.BM25 = self.original_index_dir
        vectorStore.LEGACY_BM25_DIRS = self.original_legacy_dirs
        self.temporary_directory.cleanup()

    def test_document_id_storage_and_retrieval(self):
        doc1_chunks = [
            {"text": "GET /users List all users", "metadata": {"method": "GET", "path": "/users"}},
            {"text": "POST /users Create a user", "metadata": {"method": "POST", "path": "/users"}},
        ]
        doc2_chunks = [
            {"text": "GET /orders List all orders", "metadata": {"method": "GET", "path": "/orders"}},
            {"text": "POST /orders Create an order", "metadata": {"method": "POST", "path": "/orders"}},
        ]

        # Store doc1 and doc2 with distinct document_ids
        c1 = vectorStore.store_chunks(doc1_chunks, "User API", document_id="doc_user_123")
        c2 = vectorStore.store_chunks(doc2_chunks, "Order API", document_id="doc_order_456")
        self.assertEqual(c1, 2)
        self.assertEqual(c2, 2)

        # Verify status exists
        self.assertTrue(vectorStore.has_document_index("doc_user_123"))
        self.assertTrue(vectorStore.has_document_index("doc_order_456"))
        self.assertFalse(vectorStore.has_document_index("doc_non_existent"))

        # Verify strict isolation: querying doc_user_123 must NEVER return doc2 chunks
        res1 = vectorStore.retrieve_hybrid(
            query="orders",
            document_id="doc_user_123",
            num_results=5,
        )
        for chunk in res1:
            self.assertIn("/users", chunk["metadata"]["path"])
            self.assertNotIn("/orders", chunk["metadata"]["path"])

        # Querying doc_order_456 returns order chunks
        res2 = vectorStore.retrieve_hybrid(
            query="orders",
            document_id="doc_order_456",
            num_results=5,
        )
        self.assertTrue(len(res2) > 0)
        self.assertEqual(res2[0]["metadata"]["path"], "/orders")

    def test_delete_document_index(self):
        chunks = [{"text": "GET /items List items", "metadata": {"path": "/items"}}]
        vectorStore.store_chunks(chunks, "Items API", document_id="doc_item_789")
        self.assertTrue(vectorStore.has_document_index("doc_item_789"))

        # Delete
        deleted = vectorStore.delete_document_index("doc_item_789")
        self.assertTrue(deleted)
        self.assertFalse(vectorStore.has_document_index("doc_item_789"))

        # Idempotent re-delete
        deleted_again = vectorStore.delete_document_index("doc_item_789")
        self.assertFalse(deleted_again)

    def test_ingest_file_endpoint_with_document_id(self):
        txt_content = b"This is API documentation for Authentication. Use Bearer tokens."
        data = {"document_id": "doc_custom_auth_1"}

        response = self.client.post("/ingest/file", files={"file": ("auth.txt", io.BytesIO(txt_content), "text/plain")}, data=data)
        self.assertEqual(response.status_code, 200)
        res_json = response.json()
        self.assertEqual(res_json["document_id"], "doc_custom_auth_1")
        self.assertTrue(res_json["chunks_stored"] >= 1)
        self.assertTrue(vectorStore.has_document_index("doc_custom_auth_1"))

        # Verify status endpoint
        status_res = self.client.get("/documents/doc_custom_auth_1/status")
        self.assertEqual(status_res.status_code, 200)
        status_json = status_res.json()
        self.assertTrue(status_json["exists"])
        self.assertEqual(status_json["document_id"], "doc_custom_auth_1")

        # Verify delete endpoint
        del_res = self.client.delete("/documents/doc_custom_auth_1")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["deleted"])
        self.assertFalse(vectorStore.has_document_index("doc_custom_auth_1"))

    def test_query_missing_document_id_returns_404(self):
        response = self.client.post(
            "/query",
            json={
                "question": "What is authentication?",
                "document_id": "doc_non_existent_999",
                "conversation_id": "conv_123",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    @patch("main.run_agent_graph")
    def test_query_with_document_id_and_conversation_history(self, mock_agent_graph):
        chunks = [{"text": "GET /users List users", "metadata": {"method": "GET", "path": "/users"}}]
        vectorStore.store_chunks(chunks, "Users Spec", document_id="doc_chat_test")

        from agent import AgentResult
        mock_agent_graph.return_value = AgentResult(
            answer="GET /users retrieves all active users.",
            chunks=chunks,
            confidence=95,
            attempts=1,
            retried=False,
            selected_attempt=1,
            subqueries=["GET /users parameters"],
            resolved_question="What parameters does GET /users accept?",
            selected_specs=["Users Spec"],
        )

        response = self.client.post(
            "/query",
            json={
                "question": "What parameters does it accept?",
                "document_id": "doc_chat_test",
                "conversation_id": "conv_abc",
                "history": [
                    {"question": "What is the GET /users endpoint?", "answer": "GET /users retrieves a list of users"}
                ],
                "llm_provider": "groq",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["document_id"], "doc_chat_test")
        self.assertEqual(data["conversation_id"], "conv_abc")
        self.assertEqual(data["answer"], "GET /users retrieves all active users.")
        self.assertEqual(data["confidence"], 95)
        self.assertTrue(len(data["sources"]) > 0)

    def test_invalid_document_id_format_rejected(self):
        # Path traversal or invalid characters in document_id must return 400
        res = self.client.post(
            "/query",
            json={"question": "hello", "document_id": "../../etc/passwd"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid document_id", res.json()["detail"])

        status_res = self.client.get("/documents/evil..id/status")
        self.assertEqual(status_res.status_code, 400)

        del_res = self.client.delete("/documents/evil..id")
        self.assertEqual(del_res.status_code, 400)

    def test_ssrf_blocking_private_and_localhost_urls(self):
        blocked_urls = [
            "http://127.0.0.1:8000/docs",
            "http://localhost:8000/docs",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/admin",
            "file:///etc/passwd",
        ]
        for url in blocked_urls:
            res = self.client.post("/ingest", json={"specification_url": url})
            self.assertEqual(res.status_code, 400, f"Expected 400 for blocked SSRF URL: {url}")
            detail = res.json()["detail"].lower()
            self.assertTrue(
                "forbidden" in detail or "supported" in detail or "empty" in detail,
                f"Unexpected detail message: {res.json()['detail']}",
            )

    def test_empty_question_rejected(self):
        res = self.client.post(
            "/query",
            json={"question": "   ", "document_id": "doc_test_123"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json()["detail"].lower())

    def test_file_size_limit_enforced(self):
        # 26 MB content (exceeds 25 MB limit)
        oversized = b"a" * (26 * 1024 * 1024)
        res = self.client.post(
            "/ingest/file",
            files={"file": ("large.txt", io.BytesIO(oversized), "text/plain")},
        )
        self.assertEqual(res.status_code, 413)
        self.assertIn("exceeds maximum allowed size", res.json()["detail"].lower())

    def test_list_specifications_excludes_doc_isolated_indexes(self):
        chunks = [{"text": "GET /private Private chunk", "metadata": {"path": "/private"}}]
        vectorStore.store_chunks(chunks, "Private Doc API", document_id="doc_secret_1")
        
        # Verify file doc_secret_1.pkl exists
        doc_path = vectorStore.Path(vectorStore.document_bm25_path("doc_secret_1"))
        self.assertTrue(doc_path.is_file())
        
        # Verify list_specifications does not contain "doc_secret_1" or treat it as global spec
        specs = vectorStore.list_specifications()
        for spec in specs:
            self.assertFalse(spec.startswith("doc_"))


if __name__ == "__main__":
    unittest.main()
