import { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import API_URL from "../api";
import { primaryBtnStyle, inputBaseStyle } from "../theme";
import { Spinner } from "./ui/Spinner";
import { ConfidenceRing } from "./ConfidenceRing";
import { SourceChip } from "./SourceChip";
import {
  getConversationsByDocument,
  createConversation,
  deleteConversationCascade,
  updateConversationTitle,
  getMessagesByConversation,
  saveMessage,
  getDocument,
  updateDocument,
  formatBytes,
} from "../db/indexedDB";

function cleanAnswer(answer = "") {
  return answer
    .replace(/\\([*])/g, "$1")
    .replace(/&#x20;/gi, " ")
    .replace(/&nbsp;/gi, " ");
}

export function DocumentChatView({
  document: activeDoc,
  dark,
  t,
  onBackToLibrary,
  llmProvider,
  llmProviders,
  onSelectProvider,
  onError,
}) {
  // Conversations & active state
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);

  // Recovery & index status
  const [recovering, setRecovering] = useState(false);
  const [recoveryMsg, setRecoveryMsg] = useState(null);

  // Query state
  const [question, setQuestion] = useState("");
  const [querying, setQuerying] = useState(false);
  const messagesEndRef = useRef(null);

  // Voice recording state
  const [voiceState, setVoiceState] = useState("idle");
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  // Auto-scroll to latest message
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, querying]);

  // ── 1. Check Backend Index & Auto-Recover if missing ─────────────────────────
  const checkAndRecoverBackendIndex = async () => {
    if (!activeDoc?.document_id) return;
    try {
      const res = await fetch(`${API_URL}/documents/${activeDoc.document_id}/status`);
      if (res.ok) {
        const data = await res.json();
        if (data.exists) {
          // Backend index is ready!
          return;
        }
      }

      // Backend index is missing! Trigger automatic recovery from IndexedDB
      setRecovering(true);
      setRecoveryMsg("Backend index was reset or expired. Automatically restoring from browser copy...");

      // Retrieve original document from IndexedDB
      const fullDoc = await getDocument(activeDoc.document_id);
      if (!fullDoc) {
        setRecoveryMsg("Notice: Document copy not found in browser storage.");
        return;
      }

      let restoreRes = null;
      if (fullDoc.original_file) {
        const formData = new FormData();
        formData.append("file", fullDoc.original_file, fullDoc.filename);
        formData.append("document_id", activeDoc.document_id);
        restoreRes = await fetch(`${API_URL}/ingest/file`, { method: "POST", body: formData });
      } else if (fullDoc.document_metadata?.source_url) {
        restoreRes = await fetch(`${API_URL}/ingest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            specification_url: fullDoc.document_metadata.source_url,
            document_id: activeDoc.document_id,
          }),
        });
      }

      if (restoreRes && restoreRes.ok) {
        await updateDocument(activeDoc.document_id, {
          backend_index_status: "ready",
          processing_status: "ready",
        });
        setRecoveryMsg("✓ Backend document index successfully restored.");
        setTimeout(() => setRecoveryMsg(null), 4000);
      } else {
        setRecoveryMsg("Failed to restore backend index. You may re-upload the document.");
      }
    } catch (err) {
      console.warn("Index check/recovery error:", err);
      setRecoveryMsg(null);
    } finally {
      setRecovering(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    const init = async () => {
      if (!activeDoc?.document_id) return;
      // 1. Recover index if missing
      try {
        const res = await fetch(`${API_URL}/documents/${activeDoc.document_id}/status`);
        if (res.ok) {
          const data = await res.json();
          if (!data.exists) {
            if (!ignore) {
              setRecovering(true);
              setRecoveryMsg("Backend index was reset or expired. Automatically restoring from browser copy...");
            }
            const fullDoc = await getDocument(activeDoc.document_id);
            if (fullDoc) {
              let restoreRes = null;
              if (fullDoc.original_file) {
                const formData = new FormData();
                formData.append("file", fullDoc.original_file, fullDoc.filename);
                formData.append("document_id", activeDoc.document_id);
                restoreRes = await fetch(`${API_URL}/ingest/file`, { method: "POST", body: formData });
              } else if (fullDoc.document_metadata?.source_url) {
                restoreRes = await fetch(`${API_URL}/ingest`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    specification_url: fullDoc.document_metadata.source_url,
                    document_id: activeDoc.document_id,
                  }),
                });
              }

              if (restoreRes && restoreRes.ok && !ignore) {
                await updateDocument(activeDoc.document_id, {
                  backend_index_status: "ready",
                  processing_status: "ready",
                });
                setRecoveryMsg("✓ Backend document index successfully restored.");
                setTimeout(() => {
                  if (!ignore) setRecoveryMsg(null);
                }, 4000);
              }
            }
            if (!ignore) setRecovering(false);
          }
        }
      } catch (err) {
        console.warn("Index check/recovery error:", err);
      }

      // 2. Load conversations
      try {
        let convs = await getConversationsByDocument(activeDoc.document_id);
        if (convs.length === 0) {
          const newConv = await createConversation(activeDoc.document_id, "Conversation 1");
          convs = [newConv];
        }
        if (!ignore) {
          setConversations(convs);
          setActiveConvId((curr) => (curr && convs.some(c => c.conversation_id === curr) ? curr : convs[0].conversation_id));
        }
      } catch (err) {
        console.error("Failed to load conversations:", err);
      }
    };

    init();
    return () => {
      ignore = true;
    };
  }, [activeDoc?.document_id]);

  // ── 3. Load Messages for Active Conversation ────────────────────────────────
  useEffect(() => {
    let ignore = false;
    const fetchMessages = async () => {
      if (!activeConvId) {
        if (!ignore) setMessages([]);
        return;
      }

      setLoadingMessages(true);
      try {
        const msgs = await getMessagesByConversation(activeConvId);
        if (!ignore) setMessages(msgs);
      } catch (err) {
        console.error("Failed to load messages:", err);
      } finally {
        if (!ignore) setLoadingMessages(false);
      }
    };

    fetchMessages();
    return () => {
      ignore = true;
    };
  }, [activeConvId]);

  // ── Create New Conversation ─────────────────────────────────────────────────
  const handleNewConversation = async () => {
    const nextNumber = conversations.length + 1;
    const newConv = await createConversation(activeDoc.document_id, `Conversation ${nextNumber}`);
    setConversations(prev => [newConv, ...prev]);
    setActiveConvId(newConv.conversation_id);
    setMessages([]);
  };

  // ── Delete Conversation ─────────────────────────────────────────────────────
  const handleDeleteConversation = async (convId, e) => {
    e.stopPropagation();
    const target = conversations.find(c => c.conversation_id === convId);
    const confirmDelete = window.confirm(`Delete "${target?.conversation_title || "this conversation"}"?`);
    if (!confirmDelete) return;

    try {
      await deleteConversationCascade(convId);
      const remaining = conversations.filter(c => c.conversation_id !== convId);
      setConversations(remaining);

      if (activeConvId === convId) {
        if (remaining.length > 0) {
          setActiveConvId(remaining[0].conversation_id);
        } else {
          // Create a new blank one
          const fresh = await createConversation(activeDoc.document_id, "Conversation 1");
          setConversations([fresh]);
          setActiveConvId(fresh.conversation_id);
        }
      }
    } catch (err) {
      onError({ msg: `Failed to delete conversation: ${err.message}`, hint: null });
    }
  };

  // ── 4. Query Pipeline with Context ──────────────────────────────────────────
  const handleSendQuery = async (customPrompt) => {
    const queryText = (customPrompt || question).trim();
    if (!queryText || querying || !activeConvId) return;

    setQuestion("");
    setQuerying(true);
    onError(null);

    // Save user message immediately
    const userMsg = {
      conversation_id: activeConvId,
      role: "user",
      content: queryText,
      timestamp: new Date().toISOString(),
    };
    const savedUserMsg = await saveMessage(userMsg);
    setMessages(prev => [...prev, savedUserMsg]);

    // Build conversation history (recent user-assistant pairs)
    const historyPairs = [];
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].role === "user" && messages[i + 1]?.role === "assistant") {
        historyPairs.push({
          question: messages[i].content,
          answer: messages[i + 1].content,
        });
      }
    }
    // Limit to the last 4 turns for clean bounding
    const boundedHistory = historyPairs.slice(-4);

    try {
      const res = await fetch(`${API_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: queryText,
          document_id: activeDoc.document_id,
          conversation_id: activeConvId,
          specification_name: activeDoc.document_metadata?.specification_name || activeDoc.filename,
          history: boundedHistory,
          llm_provider: llmProvider,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        // If document index was missing, report clearly
        if (res.status === 404 && data.detail?.includes("Document index")) {
          onError({
            msg: "Backend index was missing. Attempting automatic recovery...",
            hint: "Please try sending your message again in a moment.",
          });
          checkAndRecoverBackendIndex();
        } else {
          onError({ msg: data.detail || "Query failed", hint: null });
        }
        return;
      }

      // Save assistant message to IndexedDB
      const assistantMsg = {
        conversation_id: activeConvId,
        role: "assistant",
        content: data.answer,
        timestamp: new Date().toISOString(),
        source_references: data.sources || [],
        confidence_metadata: {
          confidence: data.confidence,
          attempts: data.agent?.attempts,
          retried: data.agent?.retried,
        },
        llm_metadata: data.llm || null,
      };

      const savedAssistantMsg = await saveMessage(assistantMsg);
      setMessages(prev => [...prev, savedAssistantMsg]);

      // If conversation is named "Conversation X", generate title from first query
      const currentConv = conversations.find(c => c.conversation_id === activeConvId);
      if (currentConv && currentConv.conversation_title.startsWith("Conversation ")) {
        const cleanTitle = queryText.length > 36 ? queryText.substring(0, 36) + "..." : queryText;
        await updateConversationTitle(activeConvId, cleanTitle);
        setConversations(prev =>
          prev.map(c => (c.conversation_id === activeConvId ? { ...c, conversation_title: cleanTitle } : c))
        );
      }
    } catch (err) {
      onError({ msg: err.message || "Failed to reach backend query service.", hint: null });
    } finally {
      setQuerying(false);
    }
  };

  // ── Voice Input Handler ─────────────────────────────────────────────────────
  const isRecording = voiceState === "recording";
  const isTranscribing = voiceState === "transcribing";

  const handleMic = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((trk) => trk.stop());
        setVoiceState("transcribing");
        try {
          const blob = new Blob(chunksRef.current, { type: "audio/webm" });
          const formData = new FormData();
          formData.append("file", blob, "recording.webm");

          const res = await fetch(`${API_URL}/transcribe`, {
            method: "POST",
            body: formData,
          });
          const data = await res.json();
          if (data.transcript) {
            setQuestion(data.transcript);
          }
        } catch (err) {
          console.error("Transcription error:", err);
        } finally {
          setVoiceState("idle");
        }
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceState("recording");
    } catch (err) {
      console.error("Mic access error:", err);
      setVoiceState("idle");
    }
  };

  const activeConv = conversations.find(c => c.conversation_id === activeConvId);

  return (
    <div style={{
      display: "flex",
      gap: 20,
      minHeight: "75vh",
      animation: "fadeUp 0.4s ease both",
    }}>
      {/* ── LEFT SIDEBAR: Conversations List ── */}
      <div style={{
        width: 260,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        background: t.bgCard,
        border: `1px solid ${t.borderCard}`,
        borderRadius: 16,
        padding: 16,
        boxShadow: dark ? "none" : "0 2px 16px #3b82f608",
      }}>
        {/* Back to library button */}
        <button
          onClick={onBackToLibrary}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            borderRadius: 8,
            border: `1px solid ${t.borderCard}`,
            background: t.bgCardAlt,
            color: t.textSecondary,
            fontSize: 12,
            fontFamily: "'DM Mono', monospace",
            cursor: "pointer",
            marginBottom: 14,
            transition: "color 0.2s",
          }}
        >
          <span>←</span>
          <span>All Documents</span>
        </button>

        {/* Current Document Summary Card */}
        <div style={{
          padding: 12,
          borderRadius: 10,
          background: dark ? "#ffffff05" : "#eff6ff80",
          border: `1px solid ${t.borderCard}`,
          marginBottom: 14,
        }}>
          <div style={{
            fontSize: 10,
            fontFamily: "'DM Mono', monospace",
            color: t.textLabel,
            letterSpacing: "0.1em",
            fontWeight: 700,
            marginBottom: 4,
            textTransform: "uppercase",
          }}>
            ACTIVE DOCUMENT
          </div>
          <div style={{
            fontSize: 13,
            fontWeight: 700,
            color: t.textPrimary,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            marginBottom: 4,
          }}>
            {activeDoc.filename}
          </div>
          <div style={{
            fontSize: 10,
            fontFamily: "'DM Mono', monospace",
            color: t.textMuted,
            display: "flex",
            gap: 6,
          }}>
            <span>{activeDoc.file_type.toUpperCase()}</span>
            <span>·</span>
            <span>{formatBytes(activeDoc.file_size)}</span>
          </div>
        </div>

        {/* New Chat Button */}
        <button
          onClick={handleNewConversation}
          style={{
            ...primaryBtnStyle(t, false),
            width: "100%",
            justifyContent: "center",
            padding: "10px 14px",
            marginBottom: 14,
            fontSize: 12,
          }}
        >
          <span>+ New Conversation</span>
        </button>

        {/* Conversations Label */}
        <div style={{
          fontSize: 10,
          fontFamily: "'DM Mono', monospace",
          color: t.textLabel,
          letterSpacing: "0.1em",
          fontWeight: 700,
          marginBottom: 8,
          paddingLeft: 4,
        }}>
          CONVERSATIONS ({conversations.length})
        </div>

        {/* Conversations List */}
        <div style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}>
          {conversations.map((conv) => {
            const isActive = conv.conversation_id === activeConvId;
            return (
              <div
                key={conv.conversation_id}
                onClick={() => setActiveConvId(conv.conversation_id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "9px 12px",
                  borderRadius: 8,
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "'DM Sans', sans-serif",
                  fontWeight: isActive ? 600 : 400,
                  background: isActive ? (dark ? "#3b82f620" : "#dbeafe") : "transparent",
                  color: isActive ? (dark ? "#60a5fa" : "#1d4ed8") : t.textPrimary,
                  border: isActive ? `1px solid ${dark ? "#3b82f640" : "#93c5fd"}` : "1px solid transparent",
                  transition: "background 0.15s",
                }}
              >
                <div style={{
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  flex: 1,
                  marginRight: 6,
                }}>
                  💬 {conv.conversation_title}
                </div>
                <button
                  onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                  style={{
                    background: "none",
                    border: "none",
                    color: t.textMuted,
                    fontSize: 12,
                    cursor: "pointer",
                    padding: "2px 4px",
                    borderRadius: 4,
                    opacity: 0.6,
                  }}
                  title="Delete conversation"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── MAIN CHAT AREA ── */}
      <div style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        background: t.bgCard,
        border: `1px solid ${t.borderCard}`,
        borderRadius: 16,
        padding: 24,
        boxShadow: dark ? "none" : "0 2px 16px #3b82f608",
      }}>
        {/* Chat Header */}
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          paddingBottom: 16,
          borderBottom: `1px solid ${t.borderCard}`,
          marginBottom: 16,
        }}>
          <div>
            <div style={{
              fontSize: 16,
              fontWeight: 700,
              fontFamily: "'Syne', sans-serif",
              color: t.textPrimary,
            }}>
              {activeConv?.conversation_title || "Conversation"}
            </div>
            <div style={{
              fontSize: 11,
              fontFamily: "'DM Mono', monospace",
              color: t.textSecondary,
              marginTop: 2,
            }}>
              Isolated to document: <strong>{activeDoc.filename}</strong>
            </div>
          </div>

          {/* Model selector dropdown */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", color: t.textLabel }}>
              AI MODEL:
            </span>
            <select
              value={llmProvider}
              onChange={(e) => onSelectProvider(e.target.value)}
              style={{
                background: t.inputBg,
                border: `1px solid ${t.borderInput}`,
                color: t.textPrimary,
                borderRadius: 8,
                padding: "6px 10px",
                fontSize: 12,
                fontFamily: "'DM Mono', monospace",
                cursor: "pointer",
              }}
            >
              {llmProviders.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.available}>
                  {p.label} {p.available ? "" : "(not configured)"}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Index Recovery Notice */}
        {recoveryMsg && (
          <div style={{
            background: "#f59e0b20",
            border: "1px solid #f59e0b40",
            color: "#f59e0b",
            padding: "8px 14px",
            borderRadius: 8,
            fontSize: 12,
            fontFamily: "'DM Mono', monospace",
            marginBottom: 12,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            {recovering && <Spinner size={12} />}
            <span>{recoveryMsg}</span>
          </div>
        )}

        {/* ── Messages List ── */}
        <div style={{
          flex: 1,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 18,
          paddingRight: 6,
          minHeight: 280,
          maxHeight: "56vh",
        }}>
          {loadingMessages ? (
            <div style={{ textAlign: "center", padding: 30, color: t.textSecondary }}>
              <Spinner size={16} /> Loading messages...
            </div>
          ) : messages.length === 0 ? (
            /* Empty conversation prompt */
            <div style={{
              textAlign: "center",
              padding: "40px 20px",
              color: t.textSecondary,
              margin: "auto 0",
            }}>
              <div style={{ fontSize: 28, marginBottom: 10 }}>💡</div>
              <div style={{
                fontFamily: "'Syne', sans-serif",
                fontWeight: 700,
                fontSize: 15,
                color: t.textPrimary,
                marginBottom: 6,
              }}>
                Ask anything about {activeDoc.filename}
              </div>
              <p style={{ fontSize: 13, maxWidth: 440, margin: "0 auto 16px", lineHeight: 1.6 }}>
                DocQuery grounds every answer in your documentation using BM25 retrieval and remembers conversation context for natural follow-up questions.
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8 }}>
                {[
                  "Explain all available endpoints",
                  "What authentication methods are used?",
                  "Show the request parameters and required fields",
                ].map((promptText) => (
                  <button
                    key={promptText}
                    onClick={() => handleSendQuery(promptText)}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 20,
                      border: `1px solid ${t.borderCard}`,
                      background: t.bgCardAlt,
                      color: t.textPrimary,
                      fontSize: 12,
                      cursor: "pointer",
                      fontFamily: "'DM Sans', sans-serif",
                    }}
                  >
                    "{promptText}"
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => {
              const isUser = msg.role === "user";

              if (isUser) {
                return (
                  <div
                    key={msg.message_id}
                    style={{
                      alignSelf: "flex-end",
                      maxWidth: "75%",
                      background: t.btnGradient,
                      color: "#ffffff",
                      borderRadius: "16px 16px 4px 16px",
                      padding: "12px 18px",
                      fontSize: 14,
                      lineHeight: 1.6,
                      boxShadow: dark ? "none" : "0 2px 10px #3b82f620",
                    }}
                  >
                    <div>{msg.content}</div>
                    <div style={{
                      fontSize: 10,
                      opacity: 0.7,
                      textAlign: "right",
                      marginTop: 4,
                      fontFamily: "'DM Mono', monospace",
                    }}>
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </div>
                );
              }

              // Assistant message card
              return (
                <div
                  key={msg.message_id}
                  style={{
                    alignSelf: "flex-start",
                    width: "100%",
                    background: dark ? "#ffffff04" : "#ffffff",
                    border: `1px solid ${t.borderCard}`,
                    borderRadius: "16px 16px 16px 4px",
                    padding: "20px 22px",
                    boxShadow: dark ? "none" : "0 2px 12px #3b82f608",
                  }}
                >
                  {/* Top card metadata: Confidence + Model stats */}
                  <div style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 14,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{
                        fontSize: 11,
                        fontFamily: "'DM Mono', monospace",
                        color: t.textLabel,
                        fontWeight: 700,
                        letterSpacing: "0.1em",
                      }}>
                        DOCQUERY ANSWER
                      </span>
                      {msg.llm_metadata && (
                        <span style={{
                          fontSize: 10,
                          fontFamily: "'DM Mono', monospace",
                          color: t.textMuted,
                        }}>
                          · {msg.llm_metadata.label} ({msg.llm_metadata.model})
                        </span>
                      )}
                    </div>

                    {msg.confidence_metadata?.confidence !== undefined && (
                      <ConfidenceRing value={msg.confidence_metadata.confidence} dark={dark} />
                    )}
                  </div>

                  {/* Markdown Content */}
                  <div
                    className="markdown-answer"
                    style={{
                      fontSize: 14,
                      lineHeight: 1.8,
                      color: t.textPrimary,
                      overflowWrap: "anywhere",
                    }}
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {cleanAnswer(msg.content)}
                    </ReactMarkdown>
                  </div>

                  {/* Source Citations */}
                  {msg.source_references && msg.source_references.length > 0 && (
                    <div style={{
                      marginTop: 16,
                      paddingTop: 12,
                      borderTop: `1px solid ${t.borderCard}`,
                    }}>
                      <div style={{
                        fontSize: 10,
                        fontFamily: "'DM Mono', monospace",
                        color: t.textLabel,
                        letterSpacing: "0.1em",
                        fontWeight: 700,
                        marginBottom: 8,
                      }}>
                        CITED DOCUMENTATION SOURCES:
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {msg.source_references.map((src, idx) => (
                          <SourceChip key={idx} source={src} dark={dark} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}

          {querying && (
            <div style={{
              alignSelf: "flex-start",
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "14px 20px",
              borderRadius: 14,
              background: dark ? "#ffffff05" : "#ffffff",
              border: `1px solid ${t.borderCard}`,
              color: t.textSecondary,
              fontSize: 13,
            }}>
              <Spinner size={14} />
              <span>Searching document sections & generating cited answer...</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* ── Bottom Query Input Bar ── */}
        <div style={{
          marginTop: 16,
          paddingTop: 14,
          borderTop: `1px solid ${t.borderCard}`,
        }}>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendQuery();
                }
              }}
              placeholder={`Ask a question about ${activeDoc.filename} (e.g. "What is GET /pets?" or follow-up "What parameters does it take?")...`}
              rows={2}
              disabled={querying}
              style={{
                ...inputBaseStyle(t),
                resize: "none",
                fontSize: 13,
                lineHeight: 1.5,
              }}
            />

            {/* Microphone button */}
            <button
              onClick={handleMic}
              disabled={querying}
              style={{
                width: 44,
                height: 44,
                borderRadius: 10,
                border: "none",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: isRecording ? "#ef4444" : isTranscribing ? "#f59e0b" : dark ? "#ffffff10" : "#e2e8f0",
                color: isRecording || isTranscribing ? "#fff" : t.textPrimary,
                cursor: querying ? "not-allowed" : "pointer",
                flexShrink: 0,
                transition: "background 0.2s",
              }}
              title={isRecording ? "Click to stop recording" : isTranscribing ? "Transcribing speech..." : "Voice input"}
            >
              {isTranscribing ? <Spinner size={14} /> : isRecording ? "⏹" : "🎤"}
            </button>

            {/* Send Button */}
            <button
              onClick={() => handleSendQuery()}
              disabled={querying || !question.trim()}
              style={{
                ...primaryBtnStyle(t, querying || !question.trim()),
                height: 44,
                padding: "0 20px",
              }}
            >
              {querying ? <Spinner size={14} /> : "Ask"}
            </button>
          </div>

          <div style={{
            fontSize: 11,
            color: t.textMuted,
            marginTop: 8,
            display: "flex",
            justifyContent: "space-between",
          }}>
            <span>💡 Press <strong>Enter</strong> to send · <strong>Shift+Enter</strong> for newline</span>
            <span>Follow-up question context is preserved</span>
          </div>
        </div>
      </div>
    </div>
  );
}
