import type { Observation } from "../api";

const time = (t: string) =>
  new Date(t).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export function ObservationsFeed({ observations }: { observations: Observation[] }) {
  if (!observations.length) return <p className="empty">Nessuna osservazione recente.</p>;
  return (
    <ul className="flex flex-col gap-3">
      {observations.map((o) => (
        <li key={o.url ?? `${o.title}-${o.published_at}`} className="flex flex-col gap-0.5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="font-medium">{o.source}</span>
            <span>{time(o.published_at)}</span>
            {o.symbols.map((s) => (
              <span key={s} className="px-1 rounded bg-muted">{s}</span>
            ))}
          </div>
          {o.url ? (
            <a href={o.url} target="_blank" rel="noreferrer" className="text-sm hover:underline">{o.title}</a>
          ) : (
            <span className="text-sm">{o.title}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
