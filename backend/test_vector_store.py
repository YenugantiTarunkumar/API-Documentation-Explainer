import pickle
import tempfile
import unittest
from pathlib import Path

import vectorStore
from rank_bm25 import BM25Okapi


class BM25IndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_index_dir = vectorStore.BM25
        self.original_legacy_dirs = vectorStore.LEGACY_BM25_DIRS
        self.index_dir = Path(self.temporary_directory.name) / "indexes"
        self.legacy_dir = Path(self.temporary_directory.name) / "legacy"
        self.index_dir.mkdir()
        self.legacy_dir.mkdir()
        vectorStore.BM25 = self.index_dir
        vectorStore.LEGACY_BM25_DIRS = (self.legacy_dir,)

    def tearDown(self):
        vectorStore.BM25 = self.original_index_dir
        vectorStore.LEGACY_BM25_DIRS = self.original_legacy_dirs
        self.temporary_directory.cleanup()

    def test_store_list_and_retrieve_preserve_original_name(self):
        chunks = [
            {
                "text": "GET /payments Retrieve payment details",
                "metadata": {"method": "GET", "path": "/payments"},
            },
            {
                "text": "POST /customers Create a customer",
                "metadata": {"method": "POST", "path": "/customers"},
            },
        ]

        self.assertEqual(vectorStore.store_chunks(chunks, "Payments API"), 2)
        self.assertEqual(vectorStore.list_specifications(), ["Payments API"])
        results = vectorStore.retrieve_hybrid(
            "retrieve payment details",
            "Payments API",
            num_results=2,
            rerank_top_n=2,
        )

        self.assertEqual(results[0]["metadata"]["path"], "/payments")

    def test_similarly_normalized_names_do_not_overwrite(self):
        chunks = [{"text": "GET /status Check service status", "metadata": {}}]

        self.assertNotEqual(
            vectorStore.bm25_path("API-Catalog"),
            vectorStore.bm25_path("API Catalog"),
        )
        self.assertEqual(vectorStore.store_chunks(chunks, "API-Catalog"), 1)
        self.assertEqual(vectorStore.store_chunks(chunks, "API Catalog"), 1)

        self.assertEqual(
            vectorStore.list_specifications(),
            ["API Catalog", "API-Catalog"],
        )

    def test_legacy_index_name_is_recovered_from_chunk_metadata(self):
        name = "Legacy Billing API"
        chunks = [{
            "text": "POST /invoices Create an invoice",
            "metadata": {"specification_name": name},
        }]
        legacy_index = BM25Okapi([vectorStore.tokenize(chunks[0]["text"])])
        path = self.legacy_dir / f"{vectorStore.normalize_name(name)}.pkl"
        with path.open("wb") as index_file:
            pickle.dump({"bm25": legacy_index, "chunks": chunks}, index_file)

        self.assertEqual(vectorStore.list_specifications(), [name])
        self.assertEqual(
            vectorStore.retrieve_hybrid("create invoice", name)[0]["text"],
            chunks[0]["text"],
        )

    def test_malformed_index_is_skipped(self):
        (self.index_dir / "broken.pkl").write_bytes(b"not a pickle")

        self.assertEqual(vectorStore.list_specifications(), [])


if __name__ == "__main__":
    unittest.main()
