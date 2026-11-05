import { Badge } from "./ui/Badge";
import { ThemeToggle } from "./ui/ThemeToggle";

/**
 * Sticky top header: logo, view switcher, loaded count, live indicator, theme toggle.
 */
export function AppHeader({
  dark,
  onToggleDark,
  t,
  currentView = "library",
  onSelectView,
  activeDocName = null,
}) {
  return (
    <header style={{
      padding: "16px 32px",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      borderBottom: `1px solid ${dark ? "#ffffff08" : "#dbeafe"}`,
      backdropFilter: "blur(12px)",
      position: "sticky",
      top: 0,
      zIndex: 10,
      background: t.bgHeader,
    }}>
      {/* Left: Logo + Wordmark */}
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <div
          onClick={() => onSelectView?.("library")}
          style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer" }}
        >
          <img
            src="search-icon.png"
            alt="Logo"
            style={{ width: "22px", height: "22px", objectFit: "contain" }}
          />
          <div style={{
            fontFamily: "'Syne', sans-serif",
            fontWeight: 800,
            fontSize: 20,
            letterSpacing: "-0.02em",
            color: t.textPrimary,
          }}>
            DocQuery
          </div>
        </div>

        {/* View Switcher Tabs */}
        {onSelectView && (
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: dark ? "#ffffff08" : "#e2e8f080",
            padding: "4px 6px",
            borderRadius: 10,
            border: `1px solid ${t.borderCard}`,
          }}>
            <button
              onClick={() => onSelectView("library")}
              style={{
                padding: "6px 14px",
                borderRadius: 8,
                fontSize: 12,
                fontWeight: currentView === "library" ? 700 : 500,
                fontFamily: "'DM Sans', sans-serif",
                background: currentView === "library" ? (dark ? "#3b82f620" : "#ffffff") : "transparent",
                color: currentView === "library" ? (dark ? "#60a5fa" : "#1d4ed8") : t.textSecondary,
                border: currentView === "library" ? `1px solid ${dark ? "#3b82f640" : "#cbd5e1"}` : "1px solid transparent",
                cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              📁 My Documents
            </button>

            {activeDocName && (
              <button
                onClick={() => onSelectView("chat")}
                style={{
                  padding: "6px 14px",
                  borderRadius: 8,
                  fontSize: 12,
                  fontWeight: currentView === "chat" ? 700 : 500,
                  fontFamily: "'DM Sans', sans-serif",
                  background: currentView === "chat" ? (dark ? "#3b82f620" : "#ffffff") : "transparent",
                  color: currentView === "chat" ? (dark ? "#60a5fa" : "#1d4ed8") : t.textSecondary,
                  border: currentView === "chat" ? `1px solid ${dark ? "#3b82f640" : "#cbd5e1"}` : "1px solid transparent",
                  cursor: "pointer",
                  transition: "all 0.15s",
                  maxWidth: 200,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                💬 {activeDocName}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Right-side controls */}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <Badge color="#22c55e" dark={dark}>● Live</Badge>
        <ThemeToggle dark={dark} onToggle={onToggleDark} />
      </div>
    </header>
  );
}
