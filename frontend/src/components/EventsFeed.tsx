import { useMemo, useState } from "react";
import type { AgentEvent } from "../api";
import { hm, dayLabel, price, qty } from "@/lib/format";

/* Il backend scrive gli eventi come stringhe leggibili; qui le risolleviamo in
   struttura per poterle impaginare come diario: un blocco per ciclo di decisione,
   con la nota dell'agente come titolo e le operazioni (col loro perché) annidate. */

// "ciclo decisione (LLM): <nota> — 2 operazioni, 1 saltate, 0 errori"
const DECISION_RE = /^ciclo decisione( fuori ciclo)? \(LLM\): ([\s\S]*) — (\d+) operazioni, (\d+) saltate, (\d+) errori$/;
// "ciclo decisione (LLM): errore — <eccezione>"
const DECISION_ERR_RE = /^ciclo decisione( fuori ciclo)? \(LLM\): errore — ([\s\S]*)$/;
// "BUY 378 ACTUSDT @ $0.0132 (fee $0.005)"
const TRADE_RE = /^(BUY|SELL) (\S+) (\S+) @ \$(\S+) \(fee \$(\S+)\)$/;

type Head =
  | { status: "ok"; wake: boolean; note: string; skipped: number; errors: number }
  | { status: "error"; wake: boolean; text: string }
  | { status: "raw"; wake: boolean; text: string };

function parseHead(message: string): Head {
  const ok = DECISION_RE.exec(message);
  if (ok) {
    const note = ok[2] === "(no note)" ? "" : ok[2];
    return { status: "ok", wake: !!ok[1], note, skipped: +ok[4], errors: +ok[5] };
  }
  const err = DECISION_ERR_RE.exec(message);
  if (err) return { status: "error", wake: !!err[1], text: err[2] };
  return { status: "raw", wake: false, text: message.replace(/^ciclo decisione \([^)]+\):\s*/, "") };
}

type ParsedTrade = { side: "BUY" | "SELL"; qty: string; symbol: string; price: string } | null;

const parseTrade = (message: string): ParsedTrade => {
  const m = TRADE_RE.exec(message);
  return m ? { side: m[1] as "BUY" | "SELL", qty: m[2], symbol: m[3].replace(/USDT$/, ""), price: m[4] } : null;
};

const MEMORY_SECTION_LABEL: Record<string, string> = {
  coin_theses: "tesi per coin", trade_lessons: "lezioni dai trade",
  strategy_notes: "note di strategia", self_policy: "regole",
};

type Chip = { tone: "ok" | "warn" | "err"; label: string; title?: string };

function reflectionChip(message: string): Chip {
  if (message.startsWith("memoria aggiornata")) return { tone: "ok", label: "memoria aggiornata" };
  const dist = /^memoria distillata: (\w+)$/.exec(message);
  if (dist) return { tone: "ok", label: `memoria compattata (${MEMORY_SECTION_LABEL[dist[1]] ?? dist[1]})` };
  if (message.startsWith("reflection: risposta non valida"))
    return { tone: "warn", label: "riflessione scartata: risposta non valida" };
  if (message.startsWith("reflection: errore"))
    return { tone: "err", label: "riflessione fallita", title: message };
  return { tone: "ok", label: message };
}

type Move = { trade: AgentEvent; parsed: ParsedTrade; why: string | null };
type CycleView = {
  key: string;
  timestamp: string;
  head: Head | null;          // null: gruppo senza evento decisione (es. guardrail)
  moves: Move[];
  looseWhys: string[];        // reasoning non abbinato a un trade
  reflections: Chip[];
};

// Gli eventi arrivano dal più recente; quelli con lo stesso cycle_id sono contigui.
function buildCycles(events: AgentEvent[]): CycleView[] {
  const groups: { cycleId: string | null; events: AgentEvent[] }[] = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (e.cycle_id && last && last.cycleId === e.cycle_id) last.events.push(e);
    else groups.push({ cycleId: e.cycle_id, events: [e] });
  }
  return groups.map((g, i) => {
    const chrono = [...g.events].reverse(); // dentro il ciclo: ordine di esecuzione
    const decision = chrono.find((e) => e.kind === "decision");
    const moves: Move[] = [];
    const looseWhys: string[] = [];
    for (const e of chrono) {
      if (e.kind === "trade") {
        moves.push({ trade: e, parsed: parseTrade(e.message), why: null });
      } else if (e.kind === "reasoning") {
        // il rationale viene registrato subito dopo il suo trade
        const prev = moves[moves.length - 1];
        if (prev && prev.why === null) prev.why = e.message;
        else looseWhys.push(e.message);
      }
    }
    return {
      key: g.cycleId ?? `solo-${i}`,
      timestamp: (decision ?? g.events[0]).timestamp,
      head: decision ? parseHead(decision.message) : null,
      moves,
      looseWhys,
      reflections: chrono.filter((e) => e.kind === "reflection").map((e) => reflectionChip(e.message)),
    };
  });
}

const plural = (n: number, uno: string, tanti: string) => `${n} ${n === 1 ? uno : tanti}`;

function CycleBlock({ c }: { c: CycleView }) {
  const head = c.head;
  const isErr = head?.status === "error";
  const chips: Chip[] = [];
  if (head?.status === "ok" && head.skipped > 0)
    chips.push({ tone: "warn", label: plural(head.skipped, "azione saltata", "azioni saltate"), title: "azioni proposte dal modello ma non eseguibili (es. importo sotto il minimo o coin fuori universo)" });
  if (head?.status === "ok" && head.errors > 0)
    chips.push({ tone: "err", label: plural(head.errors, "errore di esecuzione", "errori di esecuzione") });
  chips.push(...c.reflections);

  return (
    <li className="cycle">
      <header className="cycle-head">
        <time className="cycle-time num">{hm(c.timestamp)}</time>
        {head?.wake && <span className="badge badge-wake">risveglio</span>}
        {isErr && <span className="badge badge-err">errore</span>}
        {!head && <span className="badge">guardrail</span>}
        <p className={`cycle-note${isErr ? " is-err" : ""}`}>
          {head == null
            ? "operazione fuori ciclo"
            : head.status === "ok"
              ? head.note || <span className="cycle-note-none">nessuna nota dall'agente</span>
              : head.text}
        </p>
      </header>

      {(c.moves.length > 0 || c.looseWhys.length > 0) && (
        <ul className="cycle-moves">
          {c.moves.map((m, i) => (
            <li key={i} className="move">
              <span className={`tag ${m.parsed?.side === "SELL" || m.trade.message.startsWith("SELL") ? "sell" : "buy"}`}>
                {m.parsed?.side ?? (m.trade.message.startsWith("SELL") ? "SELL" : "BUY")}
              </span>
              <div className="move-body">
                <span className="move-line num">
                  {m.parsed ? (
                    <>
                      <b>{m.parsed.symbol}</b> {qty(m.parsed.qty)} @ {price(m.parsed.price)}
                    </>
                  ) : (
                    m.trade.message
                  )}
                </span>
                {m.why && <p className="move-why">{m.why}</p>}
              </div>
            </li>
          ))}
          {c.looseWhys.map((w, i) => (
            <li key={`w-${i}`} className="move">
              <span className="tag dec" aria-hidden="true">…</span>
              <div className="move-body"><p className="move-why">{w}</p></div>
            </li>
          ))}
        </ul>
      )}

      {chips.length > 0 && (
        <footer className="cycle-chips">
          {chips.map((ch, i) => (
            <span key={i} className={`chip chip-${ch.tone}`} title={ch.title}>{ch.label}</span>
          ))}
        </footer>
      )}
    </li>
  );
}

export function EventsFeed({ events }: { events: AgentEvent[] }) {
  const [onlyTrades, setOnlyTrades] = useState(false);
  const cycles = useMemo(() => buildCycles(events), [events]);
  const tradeCount = useMemo(() => cycles.reduce((n, c) => n + c.moves.length, 0), [cycles]);

  if (!events.length)
    return <p className="empty">Ancora nessuna attività. L'agente è in osservazione.</p>;

  const visible = onlyTrades ? cycles.filter((c) => c.moves.length > 0) : cycles;

  // separatori di giorno: i cicli sono già dal più recente
  const days: { label: string; cycles: CycleView[] }[] = [];
  for (const c of visible) {
    const label = dayLabel(c.timestamp);
    const last = days[days.length - 1];
    if (last && last.label === label) last.cycles.push(c);
    else days.push({ label, cycles: [c] });
  }

  return (
    <div className="feed">
      <div className="feed-bar">
        <span className="feed-count num">
          {plural(cycles.length, "ciclo", "cicli")} · {plural(tradeCount, "operazione", "operazioni")}
        </span>
        <div className="seg" role="group" aria-label="Filtra il diario">
          <button type="button" aria-pressed={!onlyTrades} onClick={() => setOnlyTrades(false)}>
            tutto
          </button>
          <button type="button" aria-pressed={onlyTrades} onClick={() => setOnlyTrades(true)}>
            solo operazioni
          </button>
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="empty">Nessun ciclo con operazioni, finora: l'agente ha sempre scelto di non muoversi.</p>
      ) : (
        <div className="feed-scroll">
          {days.map((d) => (
            <section key={d.label} className="feed-day">
              <h3 className="day-label">{d.label}</h3>
              <ol className="cycles">
                {d.cycles.map((c) => <CycleBlock key={c.key} c={c} />)}
              </ol>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
