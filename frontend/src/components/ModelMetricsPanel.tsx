import type { ModelMetrics } from "../api";

const pct = (v: string | null) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);

export function ModelMetricsPanel({ models }: { models: ModelMetrics[] }) {
  if (!models.length) {
    return (
      <div data-testid="model-metrics-panel" className="text-sm text-muted-foreground">
        Nessuna metrica per modello ancora.
      </div>
    );
  }
  // Le colonne seguono le finestre configurate nel backend (stesse per tutti i modelli)
  const windows = models[0].hit_rates.map((h) => h.window);
  return (
    <div data-testid="model-metrics-panel" className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground text-left">
            <th className="font-medium py-1 pr-4">Modello</th>
            {windows.map((w) => (
              <th key={w} className="font-medium py-1 pr-4">Hit-rate {w}</th>
            ))}
            <th className="font-medium py-1">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model_name ?? "—"} className="border-t border-border/50">
              <td className="py-1 pr-4 font-medium">{m.model_name ?? "—"}</td>
              {m.hit_rates.map((h) => (
                <td key={h.window} className="py-1 pr-4 tabular-nums">{pct(h.hit_rate)}</td>
              ))}
              <td className="py-1 tabular-nums">{m.n_scored_actions}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
