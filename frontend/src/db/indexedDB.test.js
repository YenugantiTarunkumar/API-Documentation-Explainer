import "fake-indexeddb/auto";
import assert from "node:assert/strict";
import test from "node:test";
import {
  openDB,
  saveDocument,
  getAllDocuments,
  getDocument,
  updateDocument,
  createConversation,
  getConversationsByDocument,
  updateConversationTitle,
  deleteConversationCascade,
  deleteDocumentCascade,
  saveMessage,
  getMessagesByConversation,
  formatBytes,
} from "./indexedDB.js";

test("DocQuery IndexedDB Persistence Test Suite", async (t) => {
  await t.test("1. Database initialization", async () => {
    const db = await openDB();
    assert.ok(db, "Database instance should be opened");
    assert.equal(db.name, "DocQueryDB");
    assert.ok(db.objectStoreNames.contains("documents"), "Documents store must exist");
    assert.ok(db.objectStoreNames.contains("conversations"), "Conversations store must exist");
    assert.ok(db.objectStoreNames.contains("messages"), "Messages store must exist");
  });

  await t.test("2. Saving and retrieving documents", async () => {
    const docA = {
      document_id: "doc_petstore_001",
      filename: "petstore.json",
      file_type: "json",
      file_size: 15420,
      uploaded_at: new Date().toISOString(),
      processing_status: "ready",
      backend_index_status: "ready",
      document_metadata: { specification_name: "Swagger Petstore", chunks_stored: 20 },
    };

    const docB = {
      document_id: "doc_payment_002",
      filename: "payment_spec.pdf",
      file_type: "pdf",
      file_size: 245000,
      uploaded_at: new Date().toISOString(),
      processing_status: "ready",
      backend_index_status: "ready",
      document_metadata: { specification_name: "Payment API", chunks_stored: 45 },
    };

    await saveDocument(docA);
    await saveDocument(docB);

    const allDocs = await getAllDocuments();
    assert.equal(allDocs.length, 2, "Should return 2 saved documents");

    const fetchedA = await getDocument("doc_petstore_001");
    assert.ok(fetchedA, "Should retrieve docA by ID");
    assert.equal(fetchedA.filename, "petstore.json");
    assert.equal(fetchedA.file_type, "json");
  });

  await t.test("3. Updating document metadata & recovery status", async () => {
    await updateDocument("doc_petstore_001", {
      backend_index_status: "recovering",
      processing_status: "processing",
    });

    const updated = await getDocument("doc_petstore_001");
    assert.equal(updated.backend_index_status, "recovering");
    assert.equal(updated.processing_status, "processing");

    // Restore to ready
    await updateDocument("doc_petstore_001", {
      backend_index_status: "ready",
      processing_status: "ready",
    });
    const restored = await getDocument("doc_petstore_001");
    assert.equal(restored.backend_index_status, "ready");
  });

  let testConvA1Id = null;
  let testConvA2Id = null;

  await t.test("4. Creating separate conversations for documents", async () => {
    // Document A conversations
    const convA1 = await createConversation("doc_petstore_001", "Explain all endpoints");
    const convA2 = await createConversation("doc_petstore_001", "Authentication details");
    testConvA1Id = convA1.conversation_id;
    testConvA2Id = convA2.conversation_id;

    // Document B conversations
    const convB1 = await createConversation("doc_payment_002", "Refund flow");

    assert.ok(convA1.conversation_id);
    assert.ok(convA2.conversation_id);
    assert.ok(convB1.conversation_id);

    // Verify isolation
    const petstoreConvs = await getConversationsByDocument("doc_petstore_001");
    const paymentConvs = await getConversationsByDocument("doc_payment_002");

    assert.equal(petstoreConvs.length, 2, "Petstore must have exactly 2 conversations");
    assert.equal(paymentConvs.length, 1, "Payment API must have exactly 1 conversation");

    const petstoreTitles = petstoreConvs.map((c) => c.conversation_title);
    assert.ok(petstoreTitles.includes("Explain all endpoints"));
    assert.ok(petstoreTitles.includes("Authentication details"));
    assert.ok(!petstoreTitles.includes("Refund flow"), "Document A must never contain Document B's conversations");
  });

  await t.test("5. Updating conversation title", async () => {
    await updateConversationTitle(testConvA1Id, "Updated Custom Title");
    const refreshed = await getConversationsByDocument("doc_petstore_001");
    const updatedConv = refreshed.find((c) => c.conversation_id === testConvA1Id);
    assert.equal(updatedConv.conversation_title, "Updated Custom Title");
  });

  await t.test("6. Saving and retrieving chat messages (history & follow-ups)", async () => {
    // User message 1
    await saveMessage({
      conversation_id: testConvA1Id,
      role: "user",
      content: "What is GET /pets?",
      timestamp: "2026-11-05T12:00:00Z",
    });

    // Assistant response 1
    await saveMessage({
      conversation_id: testConvA1Id,
      role: "assistant",
      content: "GET /pets returns all pets in the store.",
      timestamp: "2026-11-05T12:00:05Z",
      source_references: ["GET /pets"],
      confidence_metadata: { confidence: 95 },
    });

    // User follow-up message 2
    await saveMessage({
      conversation_id: testConvA1Id,
      role: "user",
      content: "What parameters does it take?",
      timestamp: "2026-11-05T12:00:10Z",
    });

    // Assistant response 2
    await saveMessage({
      conversation_id: testConvA1Id,
      role: "assistant",
      content: "It accepts limit and status query parameters.",
      timestamp: "2026-11-05T12:00:15Z",
      source_references: ["GET /pets query parameters"],
      confidence_metadata: { confidence: 92 },
    });

    const messages = await getMessagesByConversation(testConvA1Id);
    assert.equal(messages.length, 4, "Should have 4 messages in chronological order");
    assert.equal(messages[0].role, "user");
    assert.equal(messages[0].content, "What is GET /pets?");
    assert.equal(messages[1].role, "assistant");
    assert.equal(messages[2].content, "What parameters does it take?");
    assert.equal(messages[3].source_references[0], "GET /pets query parameters");
  });

  await t.test("7. Deleting a conversation and cascading its messages", async () => {
    // Put 1 message in convA2 as well
    await saveMessage({
      conversation_id: testConvA2Id,
      role: "user",
      content: "Tell me about auth",
      timestamp: new Date().toISOString(),
    });

    // Delete testConvA1Id (which has 4 messages)
    await deleteConversationCascade(testConvA1Id);

    // Verify testConvA1Id messages are gone
    const deletedMsgs = await getMessagesByConversation(testConvA1Id);
    assert.equal(deletedMsgs.length, 0, "Messages of deleted conversation must be purged");

    // Verify testConvA2Id is still intact
    const remainingConvs = await getConversationsByDocument("doc_petstore_001");
    assert.equal(remainingConvs.length, 1);
    assert.equal(remainingConvs[0].conversation_id, testConvA2Id);

    const keptMsgs = await getMessagesByConversation(testConvA2Id);
    assert.equal(keptMsgs.length, 1, "Unrelated conversation messages must remain unaffected");
  });

  await t.test("8. Deleting a document and cascading all conversations and messages", async () => {
    // Delete Document A
    await deleteDocumentCascade("doc_petstore_001");

    // Verify Document A is gone
    const docA = await getDocument("doc_petstore_001");
    assert.equal(docA, null, "Document A must be deleted");

    const convsA = await getConversationsByDocument("doc_petstore_001");
    assert.equal(convsA.length, 0, "All conversations of Document A must be purged");

    // Verify Document B is completely unaffected
    const docB = await getDocument("doc_payment_002");
    assert.ok(docB, "Document B must remain unaffected");

    const convsB = await getConversationsByDocument("doc_payment_002");
    assert.equal(convsB.length, 1, "Document B conversations must remain intact");
  });

  await t.test("9. Utility: formatBytes", () => {
    assert.equal(formatBytes(0), "0 B");
    assert.equal(formatBytes(1024), "1 KB");
    assert.equal(formatBytes(1048576), "1 MB");
    assert.equal(formatBytes(2621440), "2.5 MB");
  });
});
