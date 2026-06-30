import type { AgentMemory } from "../api";

const SECTIONS: { key: keyof AgentMemory; label: string }[] = [
  { key: "coin_theses", label: "Tesi per coin" },
  { key: "trade_lessons", label: "Lezioni dai trade" },
  { key: "strategy_notes", label: "Note di strategia" },
];

export function MemoryPanel({ memory }: { memory: AgentMemory }) {
  const empty = SECTIONS.every((s) => !memory[s.key].trim());
  if (empty) return <p className="text-sm text-muted-foreground">Ancora nessuna memoria. L'agente non ha chiuso trade.</p>;

  return (
    <div className="flex flex-col gap-4">
      {SECTIONS.map((s) => {
        const rows = memory[s.key].split("\n").filter((l) => l.trim());
        if (!rows.length) return null;
        return (
          <div key={s.key}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">{s.label}</h3>
            <ul className="list-disc list-inside space-y-0.5 text-sm">
              {rows.map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
