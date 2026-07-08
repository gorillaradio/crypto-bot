import type { AgentMetrics } from "../api";

const pct = (v: string | null) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);
const num = (v: string) => Number(v).toFixed(2);

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  );
}

export function MetricsPanel({ metrics }: { metrics: AgentMetrics | null }) {
  if (!metrics) {
    return (
      <div data-testid="metrics-panel" className="text-sm text-muted-foreground">
        Nessuna metrica ancora.
      </div>
    );
  }
  return (
    <div data-testid="metrics-panel" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <Stat label="Return" value={pct(metrics.return_pct)} />
      <Stat label="Max drawdown" value={pct(metrics.max_drawdown_pct)} />
      <Stat label="Sharpe" value={num(metrics.sharpe)} />
      {metrics.hit_rates.map((h) => (
        <Stat key={h.window} label={`Hit-rate ${h.window}`} value={pct(h.hit_rate)} />
      ))}
      {Object.entries(metrics.benchmarks).map(([kind, m]) => (
        <Stat key={kind} label={`${kind} return`} value={pct(m.return_pct)} />
      ))}
    </div>
  );
}
