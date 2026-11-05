import json
import sys
import time
import fitz
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

API_BASE = "http://127.0.0.1:8000"

# 1. Create a clean sample OpenAPI specification
petstore_spec = {
    "openapi": "3.0.0",
    "info": {
        "title": "Swagger Petstore Demo API",
        "version": "1.0.0",
        "description": "Sample API for managing pets in a store."
    },
    "paths": {
        "/pets": {
            "get": {
                "summary": "List all pets",
                "description": "Returns a list of pets from the system.",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "description": "How many items to return at one time (max 100)",
                        "required": False,
                        "schema": {"type": "integer", "format": "int32"}
                    },
                    {
                        "name": "status",
                        "in": "query",
                        "description": "Filter pets by status: available, pending, or sold",
                        "required": False,
                        "schema": {"type": "string", "enum": ["available", "pending", "sold"]}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "A paged array of pets",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Pet"}
                                }
                            }
                        }
                    }
                }
            },
            "post": {
                "summary": "Create a pet",
                "description": "Creates a new pet in the store.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/NewPet"}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "Null response"
                    }
                }
            }
        },
        "/pets/{petId}": {
            "get": {
                "summary": "Info for a specific pet",
                "description": "Returns a single pet by id.",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "description": "The id of the pet to retrieve",
                        "schema": {"type": "string"}
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Expected response to a valid request",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "Pet": {
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer", "format": "int64"},
                    "name": {"type": "string"},
                    "tag": {"type": "string"}
                }
            },
            "NewPet": {
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "The name of the new pet"},
                    "tag": {"type": "string", "description": "Category tag for the pet"}
                }
            }
        }
    }
}

petstore_bytes = json.dumps(petstore_spec, indent=2).encode("utf-8")

# 2. Create a clean sample PDF document
doc = fitz.open()
page = doc.new_page()
pdf_text = """Acme Cloud Billing and Invoice Guide

1. Overview
The Acme Cloud Billing service manages customer monthly invoices, payment methods, and automated usage receipts.

2. Invoicing Lifecycle
Invoices are generated on the 1st of every calendar month. Customers receive an itemized summary of compute, storage, and egress bandwidth.

3. Payment Methods
Acme Billing supports credit cards, SEPA direct debit, and wire transfers for enterprise tiers.
Late payments after 15 days incur a 2 percent penalty fee.

4. Billing Support Contact
For billing disputes, contact billing-support@acme-cloud.example.com or submit a ticket through the account portal.
"""
page.insert_text((50, 72), pdf_text, fontsize=11)
pdf_bytes = doc.tobytes()
doc.close()

def run_tests():
    print("==================================================================")
    print("STARTING COMPLETE MANUAL END-TO-END VERIFICATION")
    print("==================================================================")

    client = httpx.Client(base_url=API_BASE, timeout=60.0)

    # ── Test 1: Upload OpenAPI JSON document ──────────────────────────────────
    print("\n[Step 1] Uploading Swagger/OpenAPI JSON document...")
    res = client.post(
        "/ingest/file",
        files={"file": ("swagger_petstore.json", petstore_bytes, "application/json")},
        data={"document_id": "doc_manual_petstore_1"},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    petstore_ingest = res.json()
    print("[OK] Ingest response:", petstore_ingest)
    assert petstore_ingest["document_id"] == "doc_manual_petstore_1"
    assert petstore_ingest["chunks_stored"] >= 3

    # ── Test 2: Upload PDF document ───────────────────────────────────────────
    print("\n[Step 2] Uploading PDF document...")
    res = client.post(
        "/ingest/file",
        files={"file": ("acme_billing_guide.pdf", pdf_bytes, "application/pdf")},
        data={"document_id": "doc_manual_pdf_2"},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    pdf_ingest = res.json()
    print("[OK] Ingest response:", pdf_ingest)
    assert pdf_ingest["document_id"] == "doc_manual_pdf_2"
    assert pdf_ingest["chunks_stored"] >= 1

    # ── Test 3: Document Status Checks ────────────────────────────────────────
    print("\n[Step 3] Checking backend document status...")
    s1 = client.get("/documents/doc_manual_petstore_1/status").json()
    s2 = client.get("/documents/doc_manual_pdf_2/status").json()
    print("[OK] Petstore status:", s1)
    print("[OK] PDF guide status:", s2)
    assert s1["exists"] is True
    assert s2["exists"] is True

    # ── Test 4: Query Conversation 1 on Petstore ──────────────────────────────
    print("\n[Step 4] Query Conversation 1: Initial question on Petstore...")
    q1_payload = {
        "question": "What is the GET /pets endpoint?",
        "document_id": "doc_manual_petstore_1",
        "conversation_id": "conv_petstore_01",
        "history": [],
        "llm_provider": "groq",
    }
    t0 = time.time()
    res = client.post("/query", json=q1_payload)
    elapsed = round(time.time() - t0, 2)
    assert res.status_code == 200, f"Query failed: {res.text}"
    ans1 = res.json()
    print(f"[OK] Answer received in {elapsed}s (confidence: {ans1['confidence']}):")
    print("--- ANSWER ---")
    print(ans1["answer"])
    print("Sources:", ans1["sources"])
    assert ans1["document_id"] == "doc_manual_petstore_1"
    assert ans1["conversation_id"] == "conv_petstore_01"
    assert len(ans1["sources"]) > 0

    # ── Test 5: Follow-up Question in Conversation 1 ──────────────────────────
    print("\n[Step 5] Follow-up question in Conversation 1 (testing context awareness)...")
    q2_payload = {
        "question": "What parameters does it accept?",
        "document_id": "doc_manual_petstore_1",
        "conversation_id": "conv_petstore_01",
        "history": [
            {
                "question": "What is the GET /pets endpoint?",
                "answer": ans1["answer"]
            }
        ],
        "llm_provider": "groq",
    }
    t0 = time.time()
    res = client.post("/query", json=q2_payload)
    elapsed = round(time.time() - t0, 2)
    assert res.status_code == 200, f"Follow-up query failed: {res.text}"
    ans2 = res.json()
    print(f"[OK] Follow-up answer received in {elapsed}s (confidence: {ans2['confidence']}):")
    print("--- ANSWER ---")
    print(ans2["answer"])
    print("Resolved question:", ans2.get("agent", {}).get("resolved_question"))
    print("Sources:", ans2["sources"])
    # Verify that the answer mentions 'limit' or 'status' parameters
    assert any(param in ans2["answer"].lower() for param in ["limit", "status", "query", "parameter"])

    # ── Test 6: Separate Conversation 2 on Same Document ──────────────────────
    print("\n[Step 6] Conversation 2 on Petstore: Asking a different question...")
    q3_payload = {
        "question": "How do I create a new pet with POST /pets?",
        "document_id": "doc_manual_petstore_1",
        "conversation_id": "conv_petstore_02",
        "history": [],
        "llm_provider": "groq",
    }
    res = client.post("/query", json=q3_payload)
    assert res.status_code == 200
    ans3 = res.json()
    print("[OK] Conversation 2 Answer:")
    print("--- ANSWER ---")
    print(ans3["answer"])
    print("Sources:", ans3["sources"])
    assert ans3["conversation_id"] == "conv_petstore_02"
    assert any("post" in str(s).lower() for s in ans3["sources"])

    # ── Test 7: Strict Document Isolation ─────────────────────────────────────
    print("\n[Step 7] Testing Document Isolation: Querying PDF document...")
    q4_payload = {
        "question": "When are invoices generated and what is the late penalty fee?",
        "document_id": "doc_manual_pdf_2",
        "conversation_id": "conv_pdf_01",
        "history": [],
        "llm_provider": "groq",
    }
    res = client.post("/query", json=q4_payload)
    assert res.status_code == 200
    ans4 = res.json()
    print("[OK] PDF Guide Answer:")
    print("--- ANSWER ---")
    print(ans4["answer"])
    print("Sources:", ans4["sources"])
    assert "acme" in ans4["answer"].lower() or "invoice" in ans4["answer"].lower()

    # Document Isolation Check: Ask PDF document about "GET /pets"
    print("\n[Step 8] Testing Document Isolation: Asking PDF document about Petstore endpoints...")
    q5_payload = {
        "question": "What is the GET /pets endpoint?",
        "document_id": "doc_manual_pdf_2",
        "conversation_id": "conv_pdf_02",
        "history": [],
        "llm_provider": "groq",
    }
    res = client.post("/query", json=q5_payload)
    assert res.status_code == 200
    ans5 = res.json()
    print("[OK] Isolation test response for PDF document on unrelated query:")
    print("Sources returned:", ans5["sources"])
    for src in ans5["sources"]:
        assert "/pets" not in str(src), "Violation! Petstore endpoint chunk found in PDF document retrieval!"
    print("[OK] PASS: No Petstore chunks leaked into PDF document index.")

    # ── Test 9: Simulate Backend Index Loss & Auto-Recovery ───────────────────
    print("\n[Step 9] Simulating backend index loss (Render restart / ephemeral wipe)...")
    del_res = client.delete("/documents/doc_manual_petstore_1")
    assert del_res.status_code == 200
    status_check = client.get("/documents/doc_manual_petstore_1/status").json()
    assert status_check["exists"] is False, "Index should be missing after deletion"
    print("[OK] Successfully simulated missing index. status.exists == False")

    # Verify query returns 404 when index is missing
    missing_query_res = client.post("/query", json={
        "question": "What is GET /pets?",
        "document_id": "doc_manual_petstore_1",
    })
    assert missing_query_res.status_code == 404
    print("[OK] Server correctly returned 404 when document index was missing.")

    # Execute recovery: Re-ingest original file with exact same document_id
    print("\n[Step 10] Executing Auto-Recovery: Rebuilding index with same document_id...")
    recover_res = client.post(
        "/ingest/file",
        files={"file": ("swagger_petstore.json", petstore_bytes, "application/json")},
        data={"document_id": "doc_manual_petstore_1"},
    )
    assert recover_res.status_code == 200
    recovered_status = client.get("/documents/doc_manual_petstore_1/status").json()
    assert recovered_status["exists"] is True
    print("[OK] Document index restored. status.exists == True, chunks:", recovered_status["chunks_count"])

    # Query immediately after recovery
    after_recovery_res = client.post("/query", json={
        "question": "What is GET /pets?",
        "document_id": "doc_manual_petstore_1",
        "conversation_id": "conv_petstore_01",
        "history": [],
    })
    assert after_recovery_res.status_code == 200
    print("[OK] Query succeeded immediately following index recovery!")

    # ── Test 11: Cleanup Document Deletion ────────────────────────────────────
    print("\n[Step 11] Testing Document Deletion and Backend Cleanup...")
    client.delete("/documents/doc_manual_petstore_1")
    client.delete("/documents/doc_manual_pdf_2")
    final_s1 = client.get("/documents/doc_manual_petstore_1/status").json()
    final_s2 = client.get("/documents/doc_manual_pdf_2/status").json()
    assert final_s1["exists"] is False
    assert final_s2["exists"] is False
    print("[OK] Successfully cleaned up all test document indexes.")

    print("\n==================================================================")
    print("ALL 11 END-TO-END VERIFICATION STEPS PASSED SUCCESSFULLY!")
    print("==================================================================")

if __name__ == "__main__":
    run_tests()
