import unittest

import fitz
from backend.ingest import extract_document_chunks
from backend.sources import (
    format_chunk_reference,
    format_source,
    is_endpoint_chunk,
)


class SourceFormattingTests(unittest.TestCase):
    def test_openapi_chunk_keeps_endpoint_citation(self):
        chunk = {
            "text": "Creates a payment.",
            "metadata": {
                "method": "post",
                "path": "/payments",
                "summary": "Create payment",
                "specification_name": "Billing API",
            },
        }

        self.assertTrue(is_endpoint_chunk(chunk["metadata"]))
        self.assertEqual(
            format_chunk_reference(chunk["metadata"]),
            "POST /payments",
        )
        self.assertEqual(format_source(chunk), {
            "type": "endpoint",
            "endpoint": "POST /payments",
            "summary": "Create payment",
            "specification": "Billing API",
        })

    def test_document_chunk_includes_file_chunk_and_searchable_excerpt(self):
        chunk = {
            "text": "  Refresh the access token using the documented endpoint.  ",
            "metadata": {
                "source_file": "auth-guide.txt",
                "document_type": "txt",
                "chunk_index": 1,
                "collection_name": "auth_guide",
            },
        }

        self.assertFalse(is_endpoint_chunk(chunk["metadata"]))
        self.assertEqual(
            format_chunk_reference(chunk["metadata"]),
            "auth-guide.txt (chunk 2)",
        )
        self.assertEqual(format_source(chunk), {
            "type": "document",
            "source_file": "auth-guide.txt",
            "chunk_index": 1,
            "label": "auth-guide.txt (chunk 2)",
            "summary": "Refresh the access token using the documented endpoint.",
            "specification": "auth_guide",
        })

    def test_pdf_source_is_described_as_a_document(self):
        source = format_source({
            "text": "The PDF explains pagination.",
            "metadata": {
                "source_file": "guide.pdf",
                "document_type": "pdf",
                "chunk_index": 0,
            },
        })

        self.assertEqual(source["type"], "document")
        self.assertEqual(source["label"], "guide.pdf (chunk 1)")
        self.assertEqual(source["summary"], "The PDF explains pagination.")

    def test_txt_extraction_produces_a_document_source(self):
        chunks = extract_document_chunks(
            b"Refresh tokens expire after one hour.",
            "auth-guide.txt",
        )

        self.assertEqual(len(chunks), 1)
        source = format_source(chunks[0])
        self.assertEqual(source["type"], "document")
        self.assertEqual(source["source_file"], "auth-guide.txt")
        self.assertEqual(source["chunk_index"], 0)

    def test_pdf_extraction_produces_a_document_source(self):
        document = fitz.open()
        document.new_page().insert_text((72, 72), "Pagination uses cursor tokens.")
        pdf_bytes = document.tobytes()
        document.close()
        chunks = extract_document_chunks(pdf_bytes, "pagination.pdf")

        self.assertEqual(len(chunks), 1)
        source = format_source(chunks[0])
        self.assertEqual(source["type"], "document")
        self.assertEqual(source["label"], "pagination.pdf (chunk 1)")
        self.assertIn("cursor tokens", source["summary"])

    def test_cross_spec_source_keeps_its_collection_name(self):
        source = format_source({
            "text": "API endpoint details.",
            "metadata": {
                "method": "GET",
                "path": "/status",
                "summary": "Check status",
                "collection_name": "health_api",
            },
        })

        self.assertEqual(source["specification"], "health_api")

    def test_missing_optional_metadata_has_safe_fallbacks(self):
        chunk = {"text": "Some retrieved evidence.", "metadata": {}}

        self.assertEqual(
            format_chunk_reference(chunk["metadata"]),
            "Uploaded document chunk",
        )
        source = format_source(chunk)
        self.assertEqual(source["type"], "document")
        self.assertEqual(source["source_file"], "Uploaded document")
        self.assertEqual(source["specification"], "Unknown")
        self.assertEqual(source["summary"], "Some retrieved evidence.")


if __name__ == "__main__":
    unittest.main()
