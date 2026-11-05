import { useState, useEffect, useCallback } from "react";
import API_URL from "./src/api";
import { theme } from "./src/theme";
import { classifyError } from "./src/utils/classifyError";

import { NoiseFilter } from "./src/components/ui/NoiseFilter";
import { ErrorBanner } from "./src/components/ui/ErrorBanner";
import { AppHeader } from "./src/components/AppHeader";
import { DocumentLibrary } from "./src/components/DocumentLibrary";
import { DocumentChatView } from "./src/components/DocumentChatView";

export default function DocQuery() {
  const [dark, setDark] = useState(true);
  const t = theme(dark);

  // View state: "library" | "chat"
  const [view, setView] = useState("library");
  const [activeDoc, setActiveDoc] = useState(null);

  // LLM Providers
  const [llmProvider, setLlmProvider] = useState("groq");
  const [llmProviders, setLlmProviders] = useState([
    { id: "groq", label: "Groq", model: "openai/gpt-oss-120b", available: true },
    { id: "gemini", label: "Gemini", model: "gemini-3.8-flash", available: true },
    { id: "huggingface", label: "Hugging Face", model: "Llama 3.1 8B", available: true },
  ]);

  // Error state
  const [error, setError] = useState(null);

  const handleDocError = useCallback((err) => {
    setError(err ? classifyError(err.msg, "Document") : null);
  }, []);

  const handleQueryError = useCallback((err) => {
    setError(err ? classifyError(err.msg, "Query") : null);
  }, []);

  // Fetch available LLM providers from backend
  useEffect(() => {
    fetch(`${API_URL}/llm/providers`)
      .then((r) => r.json())
      .then((data) => {
        if (data.providers?.length) {
          setLlmProviders(data.providers);
          setLlmProvider((current) => {
            const currentIsAvailable = data.providers.some(
              (p) => p.id === current && p.available
            );
            return currentIsAvailable
              ? current
              : data.providers.find((p) => p.available)?.id || current;
          });
        }
      })
      .catch(() => {});
  }, []);

  const handleOpenDocument = (doc) => {
    setActiveDoc(doc);
    setView("chat");
    setError(null);
  };

  const handleStartNewChat = (doc) => {
    setActiveDoc(doc);
    setView("chat");
    setError(null);
  };

  const handleBackToLibrary = () => {
    setView("library");
    setError(null);
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500;600&family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes spin    { to { transform: rotate(360deg); } }
        @keyframes fadeUp  { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulseGlow { 0%,100% { box-shadow: 0 0 0 0 #3b82f622; } 50% { box-shadow: 0 0 0 8px #3b82f600; } }
        ::selection { background: #3b82f633; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: ${t.scrollThumb}; border-radius: 99px; }
        textarea:focus, input:focus { outline: none; }
        button { cursor: pointer; border: none; background: none; }
      `}</style>

      <NoiseFilter />

      <div style={{
        minHeight: "100vh",
        background: t.bg,
        fontFamily: "'DM Sans', sans-serif",
        color: t.textPrimary,
        backgroundImage: `${t.gradientRadial1}, ${t.gradientRadial2}`,
      }}>
        <AppHeader
          dark={dark}
          onToggleDark={() => setDark((d) => !d)}
          t={t}
          currentView={view}
          onSelectView={setView}
          activeDocName={activeDoc?.filename}
        />

        <main style={{
          maxWidth: view === "chat" ? 1200 : 880,
          margin: "0 auto",
          padding: "36px 24px 80px",
          transition: "max-width 0.3s ease",
        }}>
          {/* Hero Banner only shown on Library view */}
          {view === "library" && (
            <div style={{ textAlign: "center", marginBottom: 36, animation: "fadeUp 0.6s ease both" }}>
              <h1
                key={dark ? "dark-title" : "light-title"}
                style={{
                  fontFamily: "'Syne', sans-serif",
                  fontWeight: 800,
                  fontSize: "clamp(2rem, 5vw, 3rem)",
                  letterSpacing: "-0.04em",
                  lineHeight: 1.15,
                  background: dark
                    ? "linear-gradient(135deg, #e2e8f0 30%, #60a5fa 65%, #818cf8 100%)"
                    : "linear-gradient(135deg, #0f172a 30%, #3b82f6 65%, #6366f1 100%)",
                  WebkitBackgroundClip: "text",
                  backgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  color: "transparent",
                  marginBottom: 14,
                }}
              >
                API Documentation Explainer
              </h1>
              <p style={{ color: t.textSecondary, fontSize: 15, maxWidth: 540, margin: "0 auto", lineHeight: 1.7 }}>
                Store, manage, and converse with your OpenAPI specifications and documents locally in your browser. All conversations persist across browser reloads.
              </p>
            </div>
          )}

          <ErrorBanner error={error} dark={dark} />

          {view === "library" || !activeDoc ? (
            <DocumentLibrary
              dark={dark}
              t={t}
              onOpenDocument={handleOpenDocument}
              onStartNewChat={handleStartNewChat}
              onError={handleDocError}
            />
          ) : (
            <DocumentChatView
              document={activeDoc}
              dark={dark}
              t={t}
              onBackToLibrary={handleBackToLibrary}
              llmProvider={llmProvider}
              llmProviders={llmProviders}
              onSelectProvider={setLlmProvider}
              onError={handleQueryError}
            />
          )}
        </main>
      </div>
    </>
  );
}
