import {
  ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import type { EquityPoint, BenchmarkPoint } from "../api";

const fmtUsd = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

type Row = { t: number; agent?: number; randomBand?: [number, number] } & Record<string, unknown>;

export function BenchmarkChart(
  { equity, benchmarks, baseline = 100 }:
  { equity: EquityPoint[]; benchmarks: BenchmarkPoint[]; baseline?: number },
) {
  const byTs = new Map<number, Row>();
  const row = (t: number): Row => {
    let r = byTs.get(t);
    if (!r) { r = { t }; byTs.set(t, r); }
    return r;
  };
  for (const e of equity) row(new Date(e.timestamp).getTime()).agent = Number(e.equity_usd);
  for (const b of benchmarks) row(new Date(b.timestamp).getTime())[b.kind] = Number(b.equity_usd);
  const data = [...byTs.values()].sort((a, b) => a.t - b.t);
  for (const d of data) {
    const lo = d.random_p10 as number | undefined;
    const hi = d.random_p90 as number | undefined;
    if (lo != null && hi != null) d.randomBand = [lo, hi];
  }

  // One shared y-domain across every series + the $100 baseline, so agent and benchmarks are
  // directly comparable on a single scale (recharts would otherwise anchor at 0 and squash them).
  const keys = ["agent", "hodl_btc", "equal_weight", "random_p10", "random_p50", "random_p90"];
  const values = data.flatMap((d) => keys.map((k) => d[k]))
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
    .concat(baseline);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = Math.max((max - min) * 0.15, max * 0.001) || 1;

  // Equity and benchmark snapshots are sampled at slightly different instants, so most rows carry
  // only one side. connectNulls bridges those gaps so every series draws across the full history.
  return (
    <div data-testid="benchmark-chart" className="w-full h-72">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
          <YAxis domain={[min - pad, max + pad]} width={56} tickFormatter={fmtUsd}
                 tick={{ fill: "oklch(0.70 0.014 260)", fontSize: 11 }}
                 axisLine={false} tickLine={false} />
          <ReferenceLine y={baseline} stroke="oklch(0.52 0.012 260)" strokeDasharray="4 4"
                 label={{ value: `$${baseline}`, position: "insideTopLeft",
                   fill: "oklch(0.52 0.012 260)", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "oklch(0.20 0.010 260)", border: "1px solid oklch(0.30 0.014 260)",
              borderRadius: 8, fontSize: 12 }}
            labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
            formatter={(v, name) => [
              Array.isArray(v) ? `${fmtUsd(Number(v[0]))} – ${fmtUsd(Number(v[1]))}` : fmtUsd(Number(v)),
              name,
            ]} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area dataKey="randomBand" name="random (10–90%)" stroke="none"
                fill="oklch(0.62 0.02 260)" fillOpacity={0.18} connectNulls isAnimationActive={false} />
          <Line dataKey="random_p50" name="random median" stroke="oklch(0.62 0.02 260)"
                strokeDasharray="3 3" dot={false} strokeWidth={1.5} connectNulls isAnimationActive={false} />
          <Line dataKey="hodl_btc" name="HODL BTC" stroke="oklch(0.75 0.15 60)"
                dot={false} strokeWidth={1.5} connectNulls isAnimationActive={false} />
          <Line dataKey="equal_weight" name="equal-weight" stroke="oklch(0.70 0.12 200)"
                dot={false} strokeWidth={1.5} connectNulls isAnimationActive={false} />
          <Line dataKey="agent" name="agent" stroke="oklch(0.78 0.16 150)"
                dot={false} strokeWidth={2.5} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
