import { useState } from "react";
import type { AgentMemory, MemoryEntry, PolicyLine } from "../api";
import { hm, dayLabel } from "@/lib/format";

/* La memoria dell'agente in due viste:
   - "adesso": le voci attive, sezione per sezione — è ciò che entra nel prompt a ogni decisione;
   - "cronologia": il giornale completo, giorno per giorno, incluse le voci ritirate. */

type SectionKey = "coin_theses" | "trade_lessons" | "strategy_notes" | "self_policy";

const SECTIONS: { key: SectionKey; label: string; badge: string; desc: string; cap: number }[] = [
  { key: "coin_theses", label: "Tesi per coin", badge: "tesi",
    desc: "cosa pensa delle singole coin", cap: 8 },
  { key: "trade_lessons", label: "Lezioni dai trade", badge: "lezione",
    desc: "cosa ha imparato dalle operazioni chiuse", cap: 10 },
  { key: "strategy_notes", label: "Note di strategia", badge: "nota",
    desc: "principi generali che si è dato", cap: 5 },
  { key: "self_policy", label: "Regole auto-imposte", badge: "regola",
    desc: "vincoli operativi validi finché non li ritira o sostituisce", cap: 8 },
];

const badgeOf = (section: string) => SECTIONS.find((s) => s.key === section)?.badge ?? section;

function sectionRows(memory: AgentMemory, key: SectionKey): string[] | PolicyLine[] {
  if (key === "self_policy") return memory.self_policy ?? [];
  return memory[key].split("\n").filter((l) => l.trim());
}

function NowView({ memory }: { memory: AgentMemory | null }) {
  if (!memory) return <p className="empty">…</p>;

  const total = SECTIONS.reduce((n, s) => n + sectionRows(memory, s.key).length, 0);
  if (total === 0)
    return (
      <p className="empty">
        La memoria è ancora vuota: si riempie al primo trade chiuso, quando l'agente
        riflette su com'è andata e scrive cosa ha imparato.
      </p>
    );

  return (
    <div className="mem-grid">
      {SECTIONS.map((s) => {
        const rows = sectionRows(memory, s.key);
        const cap = memory.caps?.[s.key] ?? s.cap;
        return (
          <section key={s.key} aria-label={s.label}>
            <div className="mem-sec-head">
              <h3>{s.label}</h3>
              <span className="mem-fill num" title={`${rows.length} voci attive su ${cap} disponibili`}>
                {rows.length}/{cap}
              </span>
            </div>
            <p className="mem-sec-desc">{s.desc}</p>
            {rows.length === 0 ? (
              <p className="mem-sec-empty">ancora niente qui</p>
            ) : (
              <ul className="mem-list">
                {rows.map((r, i) =>
                  typeof r === "string" ? (
                    <li key={i}>{r}</li>
                  ) : (
                    <li key={r.ref}>
                      <span className="mem-ref">{r.ref}</span>
                      {r.content}
                    </li>
                  ),
                )}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

function LogView({ entries }: { entries: MemoryEntry[] }) {
  if (!entries.length)
    return <p className="empty">Cronologia vuota: la prima voce arriva col primo trade chiuso.</p>;

  // entries arrivano dalla più recente; raggruppa per giorno
  const days: { label: string; rows: MemoryEntry[] }[] = [];
  for (const e of entries) {
    const label = dayLabel(e.created_at);
    const last = days[days.length - 1];
    if (last && last.label === label) last.rows.push(e);
    else days.push({ label, rows: [e] });
  }

  return (
    <div className="mem-log">
      {days.map((d) => (
        <section key={d.label} className="mem-day">
          <h3 className="day-label">{d.label}</h3>
          <ul className="mem-rows">
            {d.rows.map((e, i) => (
              <li key={i} className={`mem-row${e.active ? "" : " retired"}`}>
                <time className="num">{hm(e.created_at)}</time>
                <span className="mem-badge">{badgeOf(e.section)}</span>
                <span className="content">{e.content}</span>
                {!e.active && <span className="chip">ritirata</span>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export function MemoryPanel({ memory, entries }: { memory: AgentMemory | null; entries: MemoryEntry[] }) {
  const [tab, setTab] = useState<"now" | "log">("now");
  const actives = entries.filter((e) => e.active).length;

  return (
    <div>
      <div className="mem-bar">
        <div className="seg" role="group" aria-label="Vista memoria">
          <button type="button" aria-pressed={tab === "now"} onClick={() => setTab("now")}>
            adesso
          </button>
          <button type="button" aria-pressed={tab === "log"} onClick={() => setTab("log")}>
            cronologia
          </button>
        </div>
        {tab === "log" && entries.length > 0 && (
          <span className="feed-count num">{entries.length} voci · {actives} attive</span>
        )}
      </div>
      <p className="mem-hint">
        {tab === "now"
          ? "Quello che l'agente sa in questo momento: queste voci entrano nel suo prompt a ogni decisione."
          : "Ogni voce nasce dalla riflessione dopo un trade chiuso. Quando una sezione supera la capienza viene compattata: le voci ritirate escono dalla memoria ma restano qui."}
      </p>
      {tab === "now" ? <NowView memory={memory} /> : <LogView entries={entries} />}
    </div>
  );
}
