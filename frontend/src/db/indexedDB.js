/**
 * IndexedDB persistence layer for DocQuery (DocQueryDB)
 * 
 * Object Stores:
 * - documents: { document_id (keyPath), filename, original_file, file_type, file_size, uploaded_at, updated_at, processing_status, document_metadata, backend_index_status }
 * - conversations: { conversation_id (keyPath), document_id, conversation_title, created_at, updated_at }
 * - messages: { message_id (keyPath), conversation_id, role, content, timestamp, source_references, confidence_metadata }
 */

const DB_NAME = "DocQueryDB";
const DB_VERSION = 1;

let dbInstance = null;

function getIDB() {
  if (typeof window !== "undefined" && window.indexedDB) {
    return window.indexedDB;
  }
  if (typeof globalThis !== "undefined" && globalThis.indexedDB) {
    return globalThis.indexedDB;
  }
  return null;
}

function getKeyRange() {
  if (typeof window !== "undefined" && window.IDBKeyRange) {
    return window.IDBKeyRange;
  }
  if (typeof globalThis !== "undefined" && globalThis.IDBKeyRange) {
    return globalThis.IDBKeyRange;
  }
  return null;
}

export function generateId(prefix = "id") {
  const timestamp = Date.now().toString(36);
  const randomPart = Math.random().toString(36).substring(2, 9);
  return `${prefix}_${timestamp}_${randomPart}`;
}

export function openDB() {
  if (dbInstance) {
    return Promise.resolve(dbInstance);
  }

  return new Promise((resolve, reject) => {
    const idb = getIDB();
    if (!idb) {
      reject(new Error("IndexedDB is not supported in this environment."));
      return;
    }

    const request = idb.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;

      // 1. Documents store
      if (!db.objectStoreNames.contains("documents")) {
        const docStore = db.createObjectStore("documents", { keyPath: "document_id" });
        docStore.createIndex("created_at", "created_at", { unique: false });
        docStore.createIndex("updated_at", "updated_at", { unique: false });
        docStore.createIndex("filename", "filename", { unique: false });
      }

      // 2. Conversations store
      if (!db.objectStoreNames.contains("conversations")) {
        const convStore = db.createObjectStore("conversations", { keyPath: "conversation_id" });
        convStore.createIndex("document_id", "document_id", { unique: false });
        convStore.createIndex("created_at", "created_at", { unique: false });
        convStore.createIndex("updated_at", "updated_at", { unique: false });
      }

      // 3. Messages store
      if (!db.objectStoreNames.contains("messages")) {
        const msgStore = db.createObjectStore("messages", { keyPath: "message_id" });
        msgStore.createIndex("conversation_id", "conversation_id", { unique: false });
        msgStore.createIndex("timestamp", "timestamp", { unique: false });
      }
    };

    request.onsuccess = (event) => {
      dbInstance = event.target.result;
      dbInstance.onversionchange = () => {
        dbInstance.close();
        dbInstance = null;
      };
      resolve(dbInstance);
    };

    request.onerror = (event) => {
      console.error("Failed to open DocQueryDB:", event.target.error);
      reject(event.target.error);
    };
  });
}

// ── Document Operations ────────────────────────────────────────────────────────

export async function saveDocument(doc) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["documents"], "readwrite");
    const store = transaction.objectStore("documents");

    const documentData = {
      document_id: doc.document_id || generateId("doc"),
      filename: doc.filename || "Untitled Document",
      original_file: doc.original_file || null, // Blob / File
      file_type: doc.file_type || "json",
      file_size: doc.file_size || 0,
      uploaded_at: doc.uploaded_at || new Date().toISOString(),
      updated_at: new Date().toISOString(),
      processing_status: doc.processing_status || "ready", // ready | processing | error | index_missing
      document_metadata: doc.document_metadata || {},
      backend_index_status: doc.backend_index_status || "ready", // ready | missing | recovering
    };

    const request = store.put(documentData);
    request.onsuccess = () => resolve(documentData);
    request.onerror = () => reject(request.error);
  });
}

export async function getAllDocuments() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["documents"], "readonly");
    const store = transaction.objectStore("documents");
    const request = store.getAll();

    request.onsuccess = () => {
      const docs = request.result || [];
      // Sort newest first
      docs.sort((a, b) => new Date(b.updated_at || b.uploaded_at) - new Date(a.updated_at || a.uploaded_at));
      resolve(docs);
    };
    request.onerror = () => reject(request.error);
  });
}

export async function getDocument(documentId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["documents"], "readonly");
    const store = transaction.objectStore("documents");
    const request = store.get(documentId);

    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

export async function updateDocument(documentId, updates) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["documents"], "readwrite");
    const store = transaction.objectStore("documents");
    const getReq = store.get(documentId);

    getReq.onsuccess = () => {
      const current = getReq.result;
      if (!current) {
        reject(new Error(`Document ${documentId} not found.`));
        return;
      }
      const updated = {
        ...current,
        ...updates,
        document_id: documentId,
        updated_at: new Date().toISOString(),
      };
      const putReq = store.put(updated);
      putReq.onsuccess = () => resolve(updated);
      putReq.onerror = () => reject(putReq.error);
    };
    getReq.onerror = () => reject(getReq.error);
  });
}

export async function deleteDocumentCascade(documentId) {
  const db = await openDB();

  // First fetch all conversation IDs for this document
  const conversations = await getConversationsByDocument(documentId);
  const convIds = conversations.map(c => c.conversation_id);

  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["documents", "conversations", "messages"], "readwrite");
    const docStore = transaction.objectStore("documents");
    const convStore = transaction.objectStore("conversations");
    const msgStore = transaction.objectStore("messages");

    // Delete document
    docStore.delete(documentId);

    // Delete conversations
    convIds.forEach(cId => convStore.delete(cId));

    // Delete messages for each conversation
    const msgIndex = msgStore.index("conversation_id");
    convIds.forEach(cId => {
      const keyRange = getKeyRange();
      const req = msgIndex.openKeyCursor(keyRange ? keyRange.only(cId) : cId);
      req.onsuccess = (e) => {
        const cursor = e.target.result;
        if (cursor) {
          msgStore.delete(cursor.primaryKey);
          cursor.continue();
        }
      };
    });

    transaction.oncomplete = () => resolve(true);
    transaction.onerror = () => reject(transaction.error);
  });
}

// ── Conversation Operations ────────────────────────────────────────────────────

export async function createConversation(documentId, initialTitle = "New Conversation") {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["conversations"], "readwrite");
    const store = transaction.objectStore("conversations");

    const conv = {
      conversation_id: generateId("conv"),
      document_id: documentId,
      conversation_title: initialTitle,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    const request = store.add(conv);
    request.onsuccess = () => resolve(conv);
    request.onerror = () => reject(request.error);
  });
}

export async function getConversationsByDocument(documentId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["conversations"], "readonly");
    const store = transaction.objectStore("conversations");
    const index = store.index("document_id");
    const keyRange = getKeyRange();
    const request = index.getAll(keyRange ? keyRange.only(documentId) : documentId);

    request.onsuccess = () => {
      const convs = request.result || [];
      convs.sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at));
      resolve(convs);
    };
    request.onerror = () => reject(request.error);
  });
}

export async function updateConversationTitle(conversationId, title) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["conversations"], "readwrite");
    const store = transaction.objectStore("conversations");
    const getReq = store.get(conversationId);

    getReq.onsuccess = () => {
      const current = getReq.result;
      if (!current) {
        reject(new Error(`Conversation ${conversationId} not found.`));
        return;
      }
      current.conversation_title = title;
      current.updated_at = new Date().toISOString();
      const putReq = store.put(current);
      putReq.onsuccess = () => resolve(current);
      putReq.onerror = () => reject(putReq.error);
    };
    getReq.onerror = () => reject(getReq.error);
  });
}

export async function deleteConversationCascade(conversationId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["conversations", "messages"], "readwrite");
    const convStore = transaction.objectStore("conversations");
    const msgStore = transaction.objectStore("messages");

    // Delete conversation
    convStore.delete(conversationId);

    // Delete all messages belonging to this conversation
    const msgIndex = msgStore.index("conversation_id");
    const keyRange = getKeyRange();
    const req = msgIndex.openKeyCursor(keyRange ? keyRange.only(conversationId) : conversationId);
    req.onsuccess = (e) => {
      const cursor = e.target.result;
      if (cursor) {
        msgStore.delete(cursor.primaryKey);
        cursor.continue();
      }
    };

    transaction.oncomplete = () => resolve(true);
    transaction.onerror = () => reject(transaction.error);
  });
}

// ── Message Operations ─────────────────────────────────────────────────────────

export async function saveMessage(msg) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["messages", "conversations"], "readwrite");
    const msgStore = transaction.objectStore("messages");
    const convStore = transaction.objectStore("conversations");

    const messageData = {
      message_id: msg.message_id || generateId("msg"),
      conversation_id: msg.conversation_id,
      role: msg.role, // "user" | "assistant"
      content: msg.content,
      timestamp: msg.timestamp || new Date().toISOString(),
      source_references: msg.source_references || [],
      confidence_metadata: msg.confidence_metadata || null,
      llm_metadata: msg.llm_metadata || null,
    };

    msgStore.put(messageData);

    // Touch conversation updated_at
    const convReq = convStore.get(msg.conversation_id);
    convReq.onsuccess = () => {
      if (convReq.result) {
        const conv = convReq.result;
        conv.updated_at = messageData.timestamp;
        convStore.put(conv);
      }
    };

    transaction.oncomplete = () => resolve(messageData);
    transaction.onerror = () => reject(transaction.error);
  });
}

export async function getMessagesByConversation(conversationId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(["messages"], "readonly");
    const store = transaction.objectStore("messages");
    const index = store.index("conversation_id");
    const keyRange = getKeyRange();
    const request = index.getAll(keyRange ? keyRange.only(conversationId) : conversationId);

    request.onsuccess = () => {
      const messages = request.result || [];
      messages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
      resolve(messages);
    };
    request.onerror = () => reject(request.error);
  });
}

// ── Storage Quota & Persistence ───────────────────────────────────────────────

export async function requestStoragePersistence() {
  if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persist) {
    try {
      const isPersisted = await navigator.storage.persist();
      return isPersisted;
    } catch {
      return false;
    }
  }
  return false;
}

export async function getStorageEstimate() {
  if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.estimate) {
    try {
      const estimate = await navigator.storage.estimate();
      return {
        usage: estimate.usage || 0,
        quota: estimate.quota || 0,
        usageFormatted: formatBytes(estimate.usage || 0),
        quotaFormatted: formatBytes(estimate.quota || 0),
        percentUsed: estimate.quota ? Math.round((estimate.usage / estimate.quota) * 100) : 0,
      };
    } catch {
      return null;
    }
  }
  return null;
}

export function formatBytes(bytes, decimals = 1) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}
