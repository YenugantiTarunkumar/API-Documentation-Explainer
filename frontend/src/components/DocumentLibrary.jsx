import { useState, useEffect } from "react";
import API_URL from "../api";
import { primaryBtnStyle, inputBaseStyle } from "../theme";
import { Spinner } from "./ui/Spinner";
import { Badge } from "./ui/Badge";
import {
  saveDocument,
  getAllDocuments,
  deleteDocumentCascade,
  getConversationsByDocument,
  requestStoragePersistence,
  getStorageEstimate,
  formatBytes,
} from "../db/indexedDB";

export function DocumentLibrary({
  dark,
  t,
  onOpenDocument,
  onStartNewChat,
  onError,
}) {
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [conversationsCount, setConversationsCount] = useState({});
  const [storageInfo, setStorageInfo] = useState(null);
  const [isPersisted, setIsPersisted] = useState(false);

  // Upload states
  const [specUrl, setSpecUrl] = useState("");
  const [specFile, setSpecFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  // Load documents and storage info on mount
  const refreshDocuments = async () => {
    try {
      const docs = await getAllDocuments();
      setDocuments(docs);

      // Load conversation counts for each document
      const counts = {};
      for (const doc of docs) {
        try {
          const convs = await getConversationsByDocument(doc.document_id);
          counts[doc.document_id] = convs.length;
        } catch {
          counts[doc.document_id] = 0;
        }
      }
      setConversationsCount(counts);

      // Check storage
      const est = await getStorageEstimate();
      setStorageInfo(est);
      if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persisted) {
        const persisted = await navigator.storage.persisted();
        setIsPersisted(persisted);
      }
    } catch (err) {
      console.error("Failed to load documents from IndexedDB:", err);
      onError({ msg: "Could not load saved documents from browser storage.", hint: null });
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    const init = async () => {
      try {
        const docs = await getAllDocuments();
        if (ignore) return;
        setDocuments(docs);

        const counts = {};
        for (const doc of docs) {
          try {
            const convs = await getConversationsByDocument(doc.document_id);
            counts[doc.document_id] = convs.length;
          } catch {
            counts[doc.document_id] = 0;
          }
        }
        if (ignore) return;
        setConversationsCount(counts);

        const est = await getStorageEstimate();
        if (ignore) return;
        setStorageInfo(est);
        if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persisted) {
          const persisted = await navigator.storage.persisted();
          if (!ignore) setIsPersisted(persisted);
        }
      } catch {
        if (!ignore && onError) {
          onError({ msg: "Could not load saved documents from browser storage.", hint: null });
        }
      } finally {
        if (!ignore) setLoadingDocs(false);
      }
    };
    init();
    return () => {
      ignore = true;
    };
  }, [onError]);

  const handleRequestPersistence = async () => {
    const granted = await requestStoragePersistence();
    setIsPersisted(granted);
    if (granted) {
      setUploadMsg("✓ Persistent browser storage granted.");
    } else {
      setUploadMsg("Browser could not grant persistent storage. Documents remain saved in standard IndexedDB.");
    }
  };

  // ── URL Ingest ─────────────────────────────────────────────────────────────
  const handleUrlIngest = async () => {
    if (!specUrl.trim()) return;
    setUploading(true);
    setUploadMsg(null);
    onError(null);
    try {
      const res = await fetch(`${API_URL}/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ specification_url: specUrl.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        onError({ msg: data.detail || "Failed to ingest URL.", hint: null });
        return;
      }

      // Fetch the actual file blob so we can store it in IndexedDB for recovery
      let fileBlob = null;
      try {
        const fileRes = await fetch(specUrl.trim());
        if (fileRes.ok) {
          fileBlob = await fileRes.blob();
        }
      } catch {
        // Fallback: create a dummy JSON blob containing the URL
        fileBlob = new Blob([JSON.stringify({ url: specUrl.trim() })], { type: "application/json" });
      }

      const docRecord = {
        document_id: data.document_id,
        filename: data.specification_name || "API Specification",
        original_file: fileBlob,
        file_type: "json",
        file_size: fileBlob ? fileBlob.size : 0,
        uploaded_at: new Date().toISOString(),
        processing_status: "ready",
        backend_index_status: "ready",
        document_metadata: {
          specification_name: data.specification_name,
          chunks_stored: data.chunks_stored,
          source_url: specUrl.trim(),
        },
      };

      await saveDocument(docRecord);
      setUploadMsg(`✓ Successfully ingested and saved "${docRecord.filename}" (${data.chunks_stored} endpoints)`);
      setSpecUrl("");
      await refreshDocuments();
    } catch (e) {
      onError({ msg: e.message, hint: "Make sure the backend is running." });
    } finally {
      setUploading(false);
    }
  };

  // ── File Ingest ────────────────────────────────────────────────────────────
  const handleFileIngest = async () => {
    if (!specFile) return;
    if (specFile.size > 25 * 1024 * 1024) {
      onError({ msg: `File size (${formatBytes(specFile.size)}) exceeds the 25 MB limit. Please select a smaller file.`, hint: null });
      return;
    }
    setUploading(true);
    setUploadMsg(null);
    onError(null);
    try {
      const ext = specFile.name.toLowerCase().rsplit ? specFile.name.toLowerCase().rsplit(".", 1)[-1] : specFile.name.split(".").pop();
      const fileType = ext === "pdf" ? "pdf" : ext === "txt" ? "txt" : "json";

      const formData = new FormData();
      formData.append("file", specFile);

      const res = await fetch(`${API_URL}/ingest/file`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        onError({ msg: data.detail || "Failed to process file.", hint: null });
        return;
      }

      const docRecord = {
        document_id: data.document_id,
        filename: specFile.name,
        original_file: specFile, // File is a Blob
        file_type: fileType,
        file_size: specFile.size,
        uploaded_at: new Date().toISOString(),
        processing_status: "ready",
        backend_index_status: "ready",
        document_metadata: {
          specification_name: data.specification_name,
          chunks_stored: data.chunks_stored,
        },
      };

      await saveDocument(docRecord);
      setUploadMsg(`✓ Saved "${specFile.name}" with ${data.chunks_stored} chunks in your local library`);
      setSpecFile(null);
      setFileInputKey(k => k + 1);
      await refreshDocuments();
    } catch (e) {
      onError({ msg: e.message, hint: "Make sure the backend is running." });
    } finally {
      setUploading(false);
    }
  };

  // ── Delete Document ────────────────────────────────────────────────────────
  const handleDeleteDocument = async (doc) => {
    const confirmDelete = window.confirm(
      `Are you sure you want to delete "${doc.filename}"?\n\nThis will permanently delete this document and all its chat conversations.`
    );
    if (!confirmDelete) return;

    setDeletingId(doc.document_id);
    try {
      // 1. Delete from backend index
      try {
        await fetch(`${API_URL}/documents/${doc.document_id}`, { method: "DELETE" });
      } catch (err) {
        console.warn("Backend deletion warning (continuing local cleanup):", err);
      }

      // 2. Cascade delete from IndexedDB
      await deleteDocumentCascade(doc.document_id);
      await refreshDocuments();
      setUploadMsg(`Deleted "${doc.filename}" and its conversations.`);
    } catch (err) {
      onError({ msg: `Failed to delete document: ${err.message}`, hint: null });
    } finally {
      setDeletingId(null);
    }
  };

  const getFileTypeColor = (type) => {
    switch (type) {
      case "json":
        return "#10b981"; // Emerald
      case "pdf":
        return "#ef4444"; // Red
      case "txt":
        return "#f59e0b"; // Amber
      default:
        return "#3b82f6"; // Blue
    }
  };

  return (
    <div style={{ animation: "fadeUp 0.5s ease both" }}>
      {/* ── Top Upload & Add Card ── */}
      <div style={{
        background: t.bgCard,
        border: `1px solid ${t.borderCard}`,
        borderRadius: 16,
        padding: 24,
        marginBottom: 28,
        boxShadow: dark ? "none" : "0 2px 16px #3b82f610",
      }}>
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}>
          <div style={{
            fontSize: 11,
            fontFamily: "'DM Mono', monospace",
            color: t.textLabel,
            letterSpacing: "0.12em",
            fontWeight: 600,
          }}>
            UPLOAD & INGEST NEW DOCUMENT
          </div>
          {storageInfo && (
            <div style={{
              fontSize: 11,
              fontFamily: "'DM Mono', monospace",
              color: t.textSecondary,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}>
              <span>Storage: {storageInfo.usageFormatted}</span>
              <span
                onClick={handleRequestPersistence}
                style={{
                  cursor: "pointer",
                  color: isPersisted ? "#10b981" : "#3b82f6",
                  textDecoration: "underline",
                }}
                title={isPersisted ? "Storage is persistent" : "Click to request persistent storage"}
              >
                {isPersisted ? "● Persistent" : "○ Request Persistence"}
              </span>
            </div>
          )}
        </div>

        {/* URL Input */}
        <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
          <input
            value={specUrl}
            onChange={(e) => setSpecUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleUrlIngest()}
            placeholder="https://petstore.swagger.io/v2/swagger.json"
            disabled={uploading}
            style={inputBaseStyle(t)}
          />
          <button
            onClick={handleUrlIngest}
            disabled={uploading || !specUrl.trim()}
            style={primaryBtnStyle(t, uploading || !specUrl.trim())}
          >
            {uploading ? <Spinner size={14} /> : "Fetch URL"}
          </button>
        </div>

        {/* Divider */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          margin: "14px 0",
          color: t.textMuted,
          fontSize: 11,
          fontFamily: "'DM Mono', monospace",
        }}>
          <div style={{ flex: 1, height: 1, background: t.borderCard }} />
          <span>OR UPLOAD LOCAL FILE</span>
          <div style={{ flex: 1, height: 1, background: t.borderCard }} />
        </div>

        {/* File Picker */}
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <input
            key={fileInputKey}
            type="file"
            accept=".json,.pdf,.txt"
            onChange={(e) => setSpecFile(e.target.files[0] || null)}
            disabled={uploading}
            style={{
              ...inputBaseStyle(t),
              padding: "9px 14px",
              cursor: "pointer",
            }}
          />
          <button
            onClick={handleFileIngest}
            disabled={uploading || !specFile}
            style={primaryBtnStyle(t, uploading || !specFile)}
          >
            {uploading ? <Spinner size={14} /> : "Upload & Save"}
          </button>
        </div>

        {uploadMsg && (
          <div style={{
            marginTop: 14,
            fontSize: 12,
            fontFamily: "'DM Mono', monospace",
            color: "#10b981",
          }}>
            {uploadMsg}
          </div>
        )}

        <div style={{
          marginTop: 16,
          paddingTop: 12,
          borderTop: `1px solid ${t.borderCard}`,
          fontSize: 11,
          color: t.textSecondary,
          lineHeight: 1.5,
        }}>
          💡 <strong>Local Storage Notice:</strong> Uploaded documents and conversation history are securely saved in your browser's IndexedDB. They survive page refreshes and browser restarts on this machine.
        </div>
      </div>

      {/* ── My Documents Section ── */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 16,
      }}>
        <div style={{
          fontFamily: "'Syne', sans-serif",
          fontWeight: 700,
          fontSize: 18,
          color: t.textPrimary,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}>
          <span>My Documents</span>
          <Badge dark={dark}>{documents.length}</Badge>
        </div>
        <button
          onClick={refreshDocuments}
          style={{
            fontSize: 12,
            fontFamily: "'DM Mono', monospace",
            color: t.accent,
            cursor: "pointer",
            background: "none",
            border: "none",
          }}
        >
          ↻ Refresh Library
        </button>
      </div>

      {loadingDocs ? (
        <div style={{
          textAlign: "center",
          padding: 40,
          color: t.textSecondary,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 10,
        }}>
          <Spinner size={16} /> Loading documents from browser storage...
        </div>
      ) : documents.length === 0 ? (
        /* Empty State */
        <div style={{
          background: t.bgCard,
          border: `1px dashed ${t.borderCard}`,
          borderRadius: 16,
          padding: "48px 24px",
          textAlign: "center",
          color: t.textSecondary,
        }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📁</div>
          <div style={{
            fontFamily: "'Syne', sans-serif",
            fontWeight: 700,
            fontSize: 16,
            color: t.textPrimary,
            marginBottom: 6,
          }}>
            No documents uploaded yet
          </div>
          <p style={{ fontSize: 13, maxWidth: 440, margin: "0 auto 16px", lineHeight: 1.6 }}>
            Upload an OpenAPI JSON specification, PDF documentation, or TXT file above to get started. Documents persist across browser sessions.
          </p>
          <button
            onClick={() => {
              setSpecUrl("https://petstore.swagger.io/v2/swagger.json");
            }}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: `1px solid ${t.borderCard}`,
              background: t.bgCardAlt,
              color: t.accent,
              fontSize: 12,
              fontFamily: "'DM Mono', monospace",
              cursor: "pointer",
            }}
          >
            Load Swagger Petstore Example
          </button>
        </div>
      ) : (
        /* Documents Grid / List */
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {documents.map((doc) => {
            const numChats = conversationsCount[doc.document_id] || 0;
            const isDeleting = deletingId === doc.document_id;
            const fileTypeColor = getFileTypeColor(doc.file_type);

            return (
              <div
                key={doc.document_id}
                style={{
                  background: t.bgCard,
                  border: `1px solid ${t.borderCard}`,
                  borderRadius: 14,
                  padding: "18px 20px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 16,
                  transition: "border-color 0.2s, transform 0.1s",
                  boxShadow: dark ? "none" : "0 2px 10px #3b82f608",
                }}
              >
                {/* Left info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                    <span
                      style={{
                        padding: "2px 7px",
                        borderRadius: 6,
                        fontSize: 10,
                        fontWeight: 700,
                        fontFamily: "'DM Mono', monospace",
                        background: `${fileTypeColor}20`,
                        color: fileTypeColor,
                        border: `1px solid ${fileTypeColor}40`,
                        textTransform: "uppercase",
                      }}
                    >
                      {doc.file_type}
                    </span>
                    <span style={{
                      fontFamily: "'Syne', sans-serif",
                      fontWeight: 700,
                      fontSize: 15,
                      color: t.textPrimary,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}>
                      {doc.filename}
                    </span>
                  </div>

                  <div style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 12,
                    fontSize: 11,
                    fontFamily: "'DM Mono', monospace",
                    color: t.textSecondary,
                  }}>
                    <span>Size: {formatBytes(doc.file_size)}</span>
                    <span>·</span>
                    <span>Uploaded: {new Date(doc.uploaded_at).toLocaleDateString()}</span>
                    <span>·</span>
                    <span>{numChats} {numChats === 1 ? "conversation" : "conversations"}</span>
                    {doc.document_metadata?.chunks_stored && (
                      <>
                        <span>·</span>
                        <span>{doc.document_metadata.chunks_stored} indexed chunks</span>
                      </>
                    )}
                  </div>
                </div>

                {/* Right action buttons */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                  <button
                    onClick={() => onOpenDocument(doc)}
                    style={{
                      padding: "8px 16px",
                      borderRadius: 8,
                      background: t.btnGradient,
                      color: "#fff",
                      fontSize: 12,
                      fontWeight: 700,
                      fontFamily: "'Syne', sans-serif",
                      cursor: "pointer",
                      border: "none",
                    }}
                  >
                    Open Chat
                  </button>

                  <button
                    onClick={() => onStartNewChat(doc)}
                    style={{
                      padding: "8px 12px",
                      borderRadius: 8,
                      border: `1px solid ${t.borderCard}`,
                      background: t.bgCardAlt,
                      color: t.textPrimary,
                      fontSize: 12,
                      fontFamily: "'Syne', sans-serif",
                      cursor: "pointer",
                    }}
                    title="Start a new conversation for this document"
                  >
                    + New Chat
                  </button>

                  <button
                    onClick={() => handleDeleteDocument(doc)}
                    disabled={isDeleting}
                    style={{
                      padding: "8px 12px",
                      borderRadius: 8,
                      border: "none",
                      background: "transparent",
                      color: "#ef4444",
                      fontSize: 12,
                      cursor: isDeleting ? "not-allowed" : "pointer",
                      opacity: isDeleting ? 0.5 : 0.8,
                    }}
                    title="Delete document and its conversations"
                  >
                    {isDeleting ? <Spinner size={12} /> : "🗑"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
