import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import type { EquityPoint } from "../api";

export function EquityChart({ data }: { data: EquityPoint[] }) {
  const points = data.map((d) => ({
    t: new Date(d.timestamp).toLocaleString(),
    equity: Number(d.equity_usd),
  }));
  return (
    <div data-testid="equity-chart" style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer>
        <LineChart data={points}>
          <XAxis dataKey="t" hide />
          <YAxis domain={["auto", "auto"]} />
          <Tooltip />
          <Line type="monotone" dataKey="equity" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
