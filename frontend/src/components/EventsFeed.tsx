import type { AgentEvent } from "../api";

export function EventsFeed({ events }: { events: AgentEvent[] }) {
  return (
    <ul>
      {events.map((e, i) => (
        <li key={i}>
          <small>{new Date(e.timestamp).toLocaleString()}</small> — [{e.kind}] {e.message}
        </li>
      ))}
    </ul>
  );
}
