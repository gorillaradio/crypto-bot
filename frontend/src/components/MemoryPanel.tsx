import type { AgentMemory } from "../api";

const SECTIONS: { key: keyof AgentMemory; label: string }[] = [
  { key: "coin_theses", label: "Tesi per coin" },
  { key: "trade_lessons", label: "Lezioni dai trade" },
  { key: "strategy_notes", label: "Note di strategia" },
];

export function MemoryPanel({ memory }: { memory: AgentMemory }) {
  const empty = SECTIONS.every((s) => !memory[s.key].trim());
  if (empty) return <p className="empty">Ancora nessuna memoria. L'agente non ha chiuso trade.</p>;

  return (
    <div className="memory">
      {SECTIONS.map((s) => {
        const rows = memory[s.key].split("\n").filter((l) => l.trim());
        if (!rows.length) return null;
        return (
          <div key={s.key} className="memory-section">
            <h3>{s.label}</h3>
            <ul>{rows.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
        );
      })}
    </div>
  );
}
