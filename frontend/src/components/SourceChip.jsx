const METHOD_COLORS = {
  GET: "#60a5fa",
  POST: "#34d399",
  PUT: "#fbbf24",
  DELETE: "#f87171",
  PATCH: "#a78bfa",
};

/**
 * Displays one API endpoint or uploaded-document source reference.
 *
 * @prop {string}      method  - HTTP method string e.g. "GET".
 * @prop {string}      path    - Endpoint path e.g. "/pets/{id}".
 * @prop {string|null} summary - Optional short description from the spec.
 * @prop {string|null} specification - Specification that supplied the endpoint.
 * @prop {boolean}     dark    - Whether dark mode is active.
 */
export function SourceChip({
  type = "endpoint",
  method,
  path,
  sourceFile,
  chunkIndex,
  summary,
  specification,
  dark,
}) {
  const isDocument = type === "document";
  const color = isDocument
    ? (dark ? "#c4b5fd" : "#7c3aed")
    : METHOD_COLORS[method] || (dark ? "#94a3b8" : "#64748b");
  const badge = isDocument ? "DOC" : method;
  const sourcePath = isDocument
    ? `${sourceFile || "Uploaded document"}${Number.isInteger(chunkIndex) ? ` · Chunk ${chunkIndex + 1}` : ""}`
    : path;
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8,
      padding: "8px 12px", borderRadius: 8,
      background: dark ? "#ffffff07" : "#00000006",
      border: `1px solid ${dark ? "#ffffff0f" : "#0000000f"}`,
    }}>
      <span style={{
        fontFamily: "'DM Mono', monospace", fontSize: 10, fontWeight: 700,
        color, background: `${color}20`, padding: "2px 7px", borderRadius: 4,
        flexShrink: 0, letterSpacing: "0.05em",
      }}>
        {badge}
      </span>
      <div>
        {specification && (
          <div style={{
            fontSize: 9, color: dark ? "#64748b" : "#94a3b8",
            fontFamily: "'DM Mono', monospace", marginBottom: 2,
            textTransform: "uppercase", letterSpacing: "0.08em",
          }}>
            {specification}
          </div>
        )}
        <div style={{
          fontFamily: "'DM Mono', monospace", fontSize: 12,
          color: dark ? "#e2e8f0" : "#1e293b",
        }}>
          {sourcePath}
        </div>
        {summary && (
          <div style={{ fontSize: 11, color: dark ? "#94a3b8" : "#64748b", marginTop: 2 }}>
            {summary}
          </div>
        )}
      </div>
    </div>
  );
}
