import type { AgentEvent } from "../api";

function eventStyle(e: AgentEvent): { color: string; label: string } {
  if (e.kind === "trade") {
    if (e.message.startsWith("BUY")) return { color: "#16a34a", label: "BUY" };
    if (e.message.startsWith("SELL")) return { color: "#dc2626", label: "SELL" };
    return { color: "#0ea5e9", label: "TRADE" };
  }
  if (e.kind === "decision") return { color: "#9ca3af", label: "DECISION" };
  return { color: "#9ca3af", label: e.kind.toUpperCase() };
}

export function EventsFeed({ events }: { events: AgentEvent[] }) {
  if (!events.length)
    return <p style={{ color: "#9ca3af" }}>Nessun evento ancora.</p>;

  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0, textAlign: "left" }}>
      {events.map((e, i) => {
        const s = eventStyle(e);
        return (
          <li
            key={i}
            style={{
              display: "flex",
              gap: 12,
              alignItems: "baseline",
              padding: "8px 12px",
              marginBottom: 6,
              borderLeft: `3px solid ${s.color}`,
              background: "rgba(127,127,127,0.06)",
              borderRadius: 4,
              fontFamily: "var(--mono)",
              fontSize: 14,
            }}
          >
            <span style={{ color: s.color, fontWeight: 600, minWidth: 78 }}>
              {s.label}
            </span>
            <span
              style={{ color: "#9ca3af", fontSize: 12, whiteSpace: "nowrap" }}
            >
              {new Date(e.timestamp).toLocaleString()}
            </span>
            <span>{e.message}</span>
          </li>
        );
      })}
    </ul>
  );
}
