import { useEffect, useMemo, useState } from "react";
import { getKlines } from "../api";

const W = 84;
const H = 28;
const PAD = 3;

// Compact 24h price trend for a coin, drawn as an SVG sparkline.
// Colour AND an arrow+sign convey direction (never colour alone — PRODUCT.md).
export function Sparkline({ symbol }: { symbol: string }) {
  const [closes, setCloses] = useState<number[] | null>(null);

  useEffect(() => {
    let alive = true;
    setCloses(null);
    getKlines(symbol)
      .then((d) => alive && setCloses(d))
      .catch(() => alive && setCloses([]));
    return () => {
      alive = false;
    };
  }, [symbol]);

  const view = useMemo(() => {
    if (!closes || closes.length < 2) return null;
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = max - min || 1;
    const path = closes
      .map((v, i) => {
        const x = PAD + (i / (closes.length - 1)) * (W - PAD * 2);
        const y = PAD + (1 - (v - min) / span) * (H - PAD * 2);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
    const first = closes[0];
    const lastV = closes[closes.length - 1];
    const up = lastV >= first;
    const pct = first ? ((lastV - first) / first) * 100 : 0;
    return { path, up, pct, lastX: W - PAD };
  }, [closes]);

  if (closes === null) return <span className="spark-skel" aria-hidden="true" />;
  if (!view) return <span className="spark-na" aria-hidden="true">—</span>;

  const cls = view.up ? "pos" : "neg";
  const lastY = (() => {
    const last = closes[closes.length - 1];
    const min = Math.min(...closes);
    const span = Math.max(...closes) - min || 1;
    return PAD + (1 - (last - min) / span) * (H - PAD * 2);
  })();

  return (
    <span className={`spark ${cls}`}>
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Andamento 24h ${view.up ? "in rialzo" : "in ribasso"} del ${Math.abs(view.pct).toFixed(1)}%`}
      >
        <path d={view.path} fill="none" strokeWidth="1.5" />
        <circle cx={view.lastX} cy={lastY} r="1.8" />
      </svg>
      <span className={`spark-pct num ${cls}`}>
        {view.up ? "▲" : "▼"} {view.up ? "+" : "−"}
        {Math.abs(view.pct).toFixed(1)}%
      </span>
    </span>
  );
}
