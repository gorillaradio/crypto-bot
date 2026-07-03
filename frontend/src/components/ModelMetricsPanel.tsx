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
  return (
    <div data-testid="model-metrics-panel" className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground text-left">
            <th className="font-medium py-1 pr-4">Modello</th>
            <th className="font-medium py-1 pr-4">Hit-rate 24h</th>
            <th className="font-medium py-1 pr-4">Hit-rate 7g</th>
            <th className="font-medium py-1">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model_name ?? "—"} className="border-t border-border/50">
              <td className="py-1 pr-4 font-medium">{m.model_name ?? "—"}</td>
              <td className="py-1 pr-4 tabular-nums">{pct(m.hit_rate_24h)}</td>
              <td className="py-1 pr-4 tabular-nums">{pct(m.hit_rate_7d)}</td>
              <td className="py-1 tabular-nums">{m.n_scored_actions}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
