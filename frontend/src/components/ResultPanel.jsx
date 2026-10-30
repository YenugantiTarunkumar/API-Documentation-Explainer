
import { useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ConfidenceRing } from "./ConfidenceRing";
import { SourceChip } from "./SourceChip";
import { useTypewriter } from "../hooks/useTypewriter";

function cleanAnswer(answer = "") {
  return answer
    .replace(/\\([*])/g, "$1")
    .replace(/&#x20;/gi, " ")
    .replace(/&nbsp;/gi, " ");
}

export function ResultPanel({ result, dark, t, animate }) {
  const answerRef = useRef(null);
  const displayedAnswer = useTypewriter(result?.answer, 12, animate);

  if (!result) return null;

  const fullAnswer = cleanAnswer(result.answer || "");
  const visibleAnswer = cleanAnswer(displayedAnswer || "");
  const isTyping = visibleAnswer.length < fullAnswer.length;

  return (
    <div style={{ animation: "fadeUp 0.5s ease both" }}>
      <div
        style={{
          background: t.bgCard,
          border: `1px solid ${t.borderCard}`,
          borderRadius: 16,
          padding: 28,
          marginBottom: 16,
          boxShadow: dark ? "none" : "0 2px 16px #3b82f610",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 20,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 11,
                fontFamily: "'DM Mono', monospace",
                color: t.textLabel,
                letterSpacing: "0.12em",
                fontWeight: 600,
              }}
            >
              ANSWER
            </div>

            {result.llm && (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 6,
                  marginTop: 8,
                  color: t.textMuted,
                  fontSize: 10,
                  fontFamily: "'DM Mono', monospace",
                }}
              >
                <span>
                  {result.llm.label} · {result.llm.model}
                </span>
                <span>· {result.latency_ms} ms</span>
                <span>
                  · {result.llm.calls} call
                  {result.llm.calls === 1 ? "" : "s"}
                </span>
                {result.llm.total_tokens > 0 && (
                  <span>· {result.llm.total_tokens} tokens</span>
                )}
                <span>· {result.llm.max_chunks} chunks max</span>
              </div>
            )}
          </div>

          <ConfidenceRing value={result.confidence} dark={dark} />
        </div>

        <div
          ref={answerRef}
          className="markdown-answer"
          style={{
            fontSize: 15,
            lineHeight: 1.8,
            color: t.textPrimary,
            minHeight: 40,
            overflowWrap: "anywhere",
          }}
        >
          {isTyping ? (
            <span style={{ whiteSpace: "pre-wrap" }}>
              {visibleAnswer}
              <span
                style={{
                  display: "inline-block",
                  width: 2,
                  height: "1em",
                  background: t.accent,
                  marginLeft: 2,
                  verticalAlign: "text-bottom",
                  animation: "blink 0.7s step-end infinite",
                }}
              />
            </span>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {fullAnswer}
            </ReactMarkdown>
          )}
        </div>
      </div>

      {result.sources?.length > 0 && (
        <div
          style={{
            background: t.bgCardAlt,
            border: `1px solid ${t.borderCard}`,
            borderRadius: 16,
            padding: 20,
            boxShadow: dark ? "none" : "0 2px 16px #3b82f610",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontFamily: "'DM Mono', monospace",
              color: t.textLabel,
              letterSpacing: "0.12em",
              marginBottom: 14,
              fontWeight: 600,
            }}
          >
            SOURCES · {result.sources.length} source
            {result.sources.length > 1 ? "s" : ""}
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {result.sources.map((s, i) => {
              const isDocument = s.type === "document";
              const [method, ...rest] = (s.endpoint || "").split(" ");

              return (
                <SourceChip
                  key={i}
                  type={s.type}
                  method={isDocument ? null : method}
                  path={isDocument ? null : rest.join(" ")}
                  sourceFile={s.source_file}
                  chunkIndex={s.chunk_index}
                  summary={s.summary}
                  specification={s.specification}
                  dark={dark}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
