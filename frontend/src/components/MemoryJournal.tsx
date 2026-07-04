import type { MemoryEntry } from "../api";

const SECTION_LABEL: Record<string, string> = {
  coin_theses: "Tesi", trade_lessons: "Lezione", strategy_notes: "Nota",
};

export function MemoryJournal({ entries }: { entries: MemoryEntry[] }) {
  if (!entries.length) {
    return <p data-testid="memory-journal" className="text-sm text-muted-foreground">Giornale vuoto.</p>;
  }
  return (
    <ul data-testid="memory-journal" className="flex flex-col gap-1 text-sm">
      {entries.map((e, i) => (
        <li key={i} className={`flex items-baseline gap-2 ${e.active ? "" : "opacity-50 line-through"}`}>
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground shrink-0">
            {SECTION_LABEL[e.section] ?? e.section}
          </span>
          <span className="flex-1">{e.content}</span>
          <time className="text-xs text-muted-foreground shrink-0 tabular-nums">
            {new Date(e.created_at).toLocaleString()}
          </time>
        </li>
      ))}
    </ul>
  );
}
