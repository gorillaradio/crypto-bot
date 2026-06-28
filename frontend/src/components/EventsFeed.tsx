import type { AgentEvent } from "../api";

function tagOf(e: AgentEvent): { cls: string; label: string } {
  if (e.kind === "trade") {
    if (e.message.startsWith("BUY")) return { cls: "buy", label: "BUY" };
    if (e.message.startsWith("SELL")) return { cls: "sell", label: "SELL" };
    return { cls: "dec", label: "TRADE" };
  }
  if (e.kind === "decision") return { cls: "dec", label: "CICLO" };
  return { cls: "dec", label: e.kind.toUpperCase() };
}

const time = (t: string) =>
  new Date(t).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function EventsFeed({ events }: { events: AgentEvent[] }) {
  if (!events.length)
    return <p className="empty">Ancora nessuna attività. L'agente è in osservazione.</p>;

  return (
    <ul className="feed">
      {events.map((e, i) => {
        const t = tagOf(e);
        return (
          <li key={i}>
            <span className={`tag ${t.cls}`}>{t.label}</span>
            <span className="body">
              <span className="time">{time(e.timestamp)}</span>
              {e.message}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
