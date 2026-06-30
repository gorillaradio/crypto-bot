import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import type { EquityPoint } from "../api";

const fmtUsd = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

export function EquityChart({ data, baseline = 100 }: { data: EquityPoint[]; baseline?: number }) {
  const points = data.map((d) => ({
    t: new Date(d.timestamp).getTime(),
    equity: Number(d.equity_usd),
  }));
  const last = points.length ? points[points.length - 1].equity : baseline;
  const up = last >= baseline;
  const color = up ? "oklch(0.78 0.16 150)" : "oklch(0.70 0.19 26)";

  const values = points.map((p) => p.equity).concat(baseline);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = Math.max((max - min) * 0.15, max * 0.001) || 1;

  return (
    <div data-testid="equity-chart" className="w-full h-72">
      <ResponsiveContainer>
        <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
          <YAxis
            domain={[min - pad, max + pad]}
            width={56}
            tick={{ fill: "oklch(0.70 0.014 260)", fontSize: 11 }}
            tickFormatter={fmtUsd}
            axisLine={false}
            tickLine={false}
          />
          <ReferenceLine
            y={baseline}
            stroke="oklch(0.52 0.012 260)"
            strokeDasharray="4 4"
            label={{ value: `$${baseline}`, position: "insideTopLeft", fill: "oklch(0.52 0.012 260)", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              background: "oklch(0.20 0.010 260)", border: "1px solid oklch(0.30 0.014 260)",
              borderRadius: 8, fontSize: 12,
            }}
            labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
            formatter={(v) => [fmtUsd(Number(v)), "Equity"]}
          />
          <Area
            type="monotone" dataKey="equity" stroke={color} strokeWidth={2}
            fill="url(#eq)" dot={false} isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
