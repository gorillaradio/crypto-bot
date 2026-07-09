import { useMemo, useState } from "react";
import type { AgentEvent, DecisionPayload, PolicyLine, RawPayload, TradePayload } from "../api";
import { hm, dayLabel, usd, pct, price, qty } from "@/lib/format";

/* Il diario risponde a "è successo questo → per questo motivo".
   Fatti in italiano generati dai payload; la voce dell'agente (inglese) è la citazione. */

type Op = { p: TradePayload; ts: string };
type Block =
  | { type: "cycle"; key: string; ts: string; head: DecisionPayload | null;
      ops: Op[]; looseWhys: string[]; guardrail: boolean; raws: string[] }
  | { type: "wait-group"; key: string; from: string; to: string;
      cycles: { ts: string; note: string }[] };

const isTrade = (p: unknown): p is TradePayload =>
  !!p && typeof p === "object" && "side" in (p as object);
const isRaw = (p: unknown): p is RawPayload =>
  !!p && typeof p === "object" && "raw" in (p as object);

function buildBlocks(events: AgentEvent[]): Block[] {
  // adiacenza di cycle_id (eventi dal più recente), come il vecchio buildCycles
  const groups: { cycleId: string | null; events: AgentEvent[] }[] = [];
  for (const e of events) {
    const last = groups[groups.length - 1];
    if (e.cycle_id && last && last.cycleId === e.cycle_id) last.events.push(e);
    else groups.push({ cycleId: e.cycle_id, events: [e] });
  }
  const cycles: Extract<Block, { type: "cycle" }>[] = groups.map((g, i) => {
    const chrono = [...g.events].reverse();
    const decision = chrono.find((e) => e.kind === "decision");
    const ops: Op[] = [];
    const looseWhys: string[] = [];
    const raws: string[] = [];
    for (const e of chrono) {
      if (e.kind === "reflection") continue;                     // dominio striscia salute
      const p = e.payload;
      if (e.kind === "trade" && isTrade(p)) ops.push({ p, ts: e.timestamp });
      else if (e.kind === "reasoning" && isRaw(p)) { if (!p.folded) looseWhys.push(p.raw); }
      else if (e.kind === "decision" && p && !isRaw(p)) { /* head, sotto */ }
      else raws.push(isRaw(p) ? p.raw : e.message);              // legacy/non interpretato
    }
    const head = decision && decision.payload && !isRaw(decision.payload)
      ? (decision.payload as DecisionPayload) : null;
    // (un decision con payload null/raw è già finito in `raws` dentro il loop)
    return { type: "cycle" as const, key: g.cycleId ?? `solo-${i}`,
             ts: (decision ?? g.events[0]).timestamp, head, ops, looseWhys,
             guardrail: !g.cycleId, raws };
  });

  // cicli fermi consecutivi (ok, senza ops né righe grezze) → gruppo unico
  const out: Block[] = [];
  for (const c of cycles) {
    const idle = c.head?.status === "ok" && c.ops.length === 0 && c.raws.length === 0
      && !c.guardrail && !c.head?.wake_reason;
    const prev = out[out.length - 1];
    if (idle && prev?.type === "wait-group") {
      prev.cycles.push({ ts: c.ts, note: c.head?.note ?? "" });
      prev.from = c.ts;                                          // eventi desc: from = più vecchio
    } else if (idle) {
      out.push({ type: "wait-group", key: `w-${c.key}`, from: c.ts, to: c.ts,
                 cycles: [{ ts: c.ts, note: c.head?.note ?? "" }] });
    } else out.push(c);
  }
  return out;
}

/* PERCHÉ: la citazione, coi riferimenti P#### risolti in tooltip. */
function Quote({ text, policy }: { text: string; policy: PolicyLine[] }) {
  if (!text) return <span className="quote-none">nessuna nota dall'agente</span>;
  const parts = text.split(/(P\d{1,6})/g);
  return (
    <span className="quote">
      {parts.map((part, i) => {
        const hit = /^P\d{1,6}$/.test(part) ? policy.find((l) => l.ref === part) : undefined;
        return hit
          ? <abbr key={i} className="policy-ref" title={hit.content}>{part}</abbr>
          : <span key={i}>{part}</span>;
      })}
    </span>
  );
}

function Why({ note, policy }: { note: string; policy: PolicyLine[] }) {
  return (
    <p className="why-line">
      <span className="why-label">PERCHÉ</span> <Quote text={note} policy={policy} />
    </p>
  );
}

const sym = (s: string) => s.replace(/USDT$/, "");
const pnlCls = (n: number) => (n >= 0 ? "pos" : "neg");

function OpRow({ op, policy }: { op: Op; policy: PolicyLine[] }) {
  const p = op.p;
  const sell = p.side === "SELL";
  const frac = p.fraction != null ? Number(p.fraction) : null;
  const partial = sell && frac != null && frac < 0.995;
  const pnlPct = p.realized_pnl_pct != null ? Number(p.realized_pnl_pct) : null;
  const pnlUsd = p.realized_pnl_usd != null ? Number(p.realized_pnl_usd) : null;
  return (
    <li className="op-row">
      <span className="side-pill">{sell ? "VENDITA" : "ACQUISTO"}</span>
      <a className="op-sym" href={p.position_summary ? `#pos-closed-${sym(p.symbol)}` : `#pos-${sym(p.symbol)}`}>
        {sym(p.symbol)}
      </a>
      {partial && <span className="op-frac num">venduto il {Math.round(frac! * 100)}%</span>}
      {sell && pnlPct != null && (
        <span className={`num ${pnlCls(pnlPct)}`}>
          {pct(pnlPct)}{pnlUsd != null && <> {pnlUsd >= 0 ? "+" : "−"}{usd(Math.abs(pnlUsd))}</>}
        </span>
      )}
      {!sell && p.usd_value != null && (
        <span className="op-frac num">
          ~{usd(p.usd_value)}
          {p.position === "new" && " · nuova posizione"}
          {p.position === "increase" && " · posizione aumentata"}
        </span>
      )}
      {sell && pnlPct == null && (
        <span className="op-frac num">{qty(p.qty)} @ {price(p.price)}</span>
      )}
      <details className="op-details">
        <summary>dettagli</summary>
        <p className="num">
          qty {qty(p.qty)} @ {price(p.price)} · fee {usd(p.fee)}
          {p.avg_cost != null && <> · costo medio {price(p.avg_cost)}</>}
        </p>
        {p.rationale && <Quote text={p.rationale} policy={policy} />}
      </details>
    </li>
  );
}

function CycleBlock({ c, policy }: { c: Extract<Block, { type: "cycle" }>; policy: PolicyLine[] }) {
  const err = c.head?.status === "error";
  return (
    <li className="cycle" id={c.guardrail ? undefined : `cycle-${c.key}`}>
      <header className="cycle-head">
        <time className="cycle-time num">{hm(c.ts)}</time>
        {c.head?.wake_reason && <span className="badge">risveglio</span>}
        {err && <span className="fact is-err">Ciclo fallito{c.head?.detail ? ` — ${c.head.detail}` : ""}</span>}
      </header>
      {c.guardrail && c.ops.length > 0 && (
        <p className="fact-quiet">Intervento automatico (guardrail)</p>
      )}
      {c.ops.length > 0 && (
        <ul className="cycle-ops">{c.ops.map((op, i) => <OpRow key={i} op={op} policy={policy} />)}</ul>
      )}
      {c.head?.status === "ok" && c.ops.length === 0 && !c.guardrail && (
        <p className="fact-quiet">Nessuna mossa</p>
      )}
      {c.head?.status === "ok" && <Why note={c.head.note ?? ""} policy={policy} />}
      {c.looseWhys.map((w, i) => <p key={i} className="why-line"><Quote text={w} policy={policy} /></p>)}
      {c.raws.map((r, i) => <p key={`r-${i}`} className="raw-line">{r}</p>)}
    </li>
  );
}

function WaitGroup({ g, policy }: { g: Extract<Block, { type: "wait-group" }>; policy: PolicyLine[] }) {
  const newest = g.cycles[0];
  const range = g.cycles.length > 1 ? `${hm(g.from)}–${hm(g.to)}` : hm(g.to);
  return (
    <li className="cycle waitrow">
      <header className="cycle-head">
        <time className="cycle-time num">{range}</time>
        <span className="fact-quiet">
          Nessuna mossa{g.cycles.length > 1 && <span className="num"> ({g.cycles.length} cicli)</span>}
        </span>
      </header>
      <Why note={newest.note} policy={policy} />
      {g.cycles.length > 1 && (
        <details className="op-details">
          <summary>i singoli cicli</summary>
          {/* la nota più recente è già nel PERCHÉ sopra: qui solo le precedenti */}
          <ul>{g.cycles.slice(1).map((c, i) => (
            <li key={i} className="raw-line"><span className="num">{hm(c.ts)}</span> — <Quote text={c.note} policy={policy} /></li>
          ))}</ul>
        </details>
      )}
    </li>
  );
}

const plural = (n: number, uno: string, tanti: string) => `${n} ${n === 1 ? uno : tanti}`;

export function EventsFeed({ events, policy }: { events: AgentEvent[]; policy: PolicyLine[] }) {
  const [onlyTrades, setOnlyTrades] = useState(false);
  const blocks = useMemo(() => buildBlocks(events), [events]);
  const { cycleCount, tradeCount } = useMemo(() => ({
    cycleCount: blocks.reduce((n, b) => n + (b.type === "wait-group" ? b.cycles.length : 1), 0),
    tradeCount: blocks.reduce((n, b) => n + (b.type === "cycle" ? b.ops.length : 0), 0),
  }), [blocks]);

  if (!events.length)
    return <p className="empty">Ancora nessuna attività. L'agente è in osservazione.</p>;

  const visible = onlyTrades
    ? blocks.filter((b) => b.type === "cycle" && b.ops.length > 0)
    : blocks;

  const days: { label: string; blocks: Block[] }[] = [];
  for (const b of visible) {
    const label = dayLabel(b.type === "wait-group" ? b.to : b.ts);
    const last = days[days.length - 1];
    if (last && last.label === label) last.blocks.push(b);
    else days.push({ label, blocks: [b] });
  }

  return (
    <div className="feed">
      <div className="feed-bar">
        <span className="feed-count num">
          {plural(cycleCount, "ciclo", "cicli")} · {plural(tradeCount, "operazione", "operazioni")}
        </span>
        <div className="seg" role="group" aria-label="Filtra il diario">
          <button type="button" aria-pressed={!onlyTrades} onClick={() => setOnlyTrades(false)}>tutto</button>
          <button type="button" aria-pressed={onlyTrades} onClick={() => setOnlyTrades(true)}>solo operazioni</button>
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
                {d.blocks.map((b) => b.type === "wait-group"
                  ? <WaitGroup key={b.key} g={b} policy={policy} />
                  : <CycleBlock key={b.key} c={b} policy={policy} />)}
              </ol>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
