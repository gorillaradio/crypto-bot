import type { AgentEvent } from "../api";

function tradeTag(e: AgentEvent): { cls: string; label: string } {
  if (e.message.startsWith("BUY")) return { cls: "buy", label: "BUY" };
  if (e.message.startsWith("SELL")) return { cls: "sell", label: "SELL" };
  return { cls: "dec", label: "TRADE" };
}

const time = (t: string) =>
  new Date(t).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

// "ciclo decisione (LLM): <nota> — <conteggi>" → "<nota> — <conteggi>"
const decisionText = (m: string) => m.replace(/^ciclo decisione \([^)]+\):\s*/, "");

type Cycle = { cycleId: string | null; events: AgentEvent[] };

// Events sharing a cycle_id arrive contiguous (same timestamp, stable order); a null
// cycle_id (e.g. a heartbeat guardrail sell) is always its own standalone group.
function groupByCycle(events: AgentEvent[]): Cycle[] {
  const cycles: Cycle[] = [];
  for (const e of events) {
    const last = cycles[cycles.length - 1];
    if (e.cycle_id && last && last.cycleId === e.cycle_id) last.events.push(e);
    else cycles.push({ cycleId: e.cycle_id, events: [e] });
  }
  return cycles;
}

export function EventsFeed({ events }: { events: AgentEvent[] }) {
  if (!events.length)
    return <p className="empty">Ancora nessuna attività. L'agente è in osservazione.</p>;

  return (
    <div className="feed">
      {groupByCycle(events).map((c, ci) => {
        const decision = c.events.find((e) => e.kind === "decision");
        const reflection = c.events.find((e) => e.kind === "reflection");
        const moves = c.events.filter((e) => e.kind !== "decision" && e.kind !== "reflection");
        return (
          <section className="cycle" key={c.cycleId ?? `solo-${ci}`}>
            {decision && (
              <header className="cycle-head">
                <span className="cycle-time num">{time(decision.timestamp)}</span>
                <span className="cycle-summary">{decisionText(decision.message)}</span>
              </header>
            )}
            {moves.length > 0 && (
              <ul className={`cycle-moves${decision ? "" : " bare"}`}>
                {moves.map((e, i) =>
                  e.kind === "trade" ? (
                    <li key={i} className="move">
                      <span className={`tag ${tradeTag(e).cls}`}>{tradeTag(e).label}</span>
                      <span className="body">
                        {!decision && <span className="time num">{time(e.timestamp)}</span>}
                        {e.message}
                      </span>
                    </li>
                  ) : (
                    <li key={i} className="reason">{e.message}</li>
                  )
                )}
              </ul>
            )}
            {reflection && <div className="cycle-foot">{reflection.message}</div>}
          </section>
        );
      })}
    </div>
  );
}
