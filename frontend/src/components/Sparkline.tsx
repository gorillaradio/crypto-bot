const W = 84;
const H = 28;
const PAD = 3;

// Compact 24h price trend for a coin, drawn as an SVG sparkline.
// Colour AND an arrow+sign convey direction (never colour alone — PRODUCT.md).
export function Sparkline({ closes }: { symbol: string; closes: number[] | null }) {
  // Not enough data: 84px wide faint em-dash placeholder
  if (!closes || closes.length < 2)
    return <span className="spark-na inline-block w-21 text-muted-foreground" aria-hidden="true">—</span>;

  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const path = closes
    .map((value, index) => {
      const x = PAD + (index / (closes.length - 1)) * (W - PAD * 2);
      const y = PAD + (1 - (value - min) / span) * (H - PAD * 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const first = closes[0];
  const last = closes[closes.length - 1];
  const up = last >= first;
  const pct = first ? ((last - first) / first) * 100 : 0;
  const lastY = PAD + (1 - (last - min) / span) * (H - PAD * 2);

  const cls = up ? "pos" : "neg";

  return (
    // .spark: inline-flex, items-center, gap-8px; .pos/.neg apply the green/red color
    // from index.css (.pos { color: var(--pos) } / .neg { color: var(--neg) })
    <span className={`spark ${cls} inline-flex items-center gap-2`}>
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Andamento 24h ${up ? "in rialzo" : "in ribasso"} del ${Math.abs(pct).toFixed(1)}%`}
        // SVG path/circle inherit currentColor from .pos/.neg on parent span
        className="[&_path]:stroke-current [&_path]:stroke-linecap-round [&_path]:stroke-linejoin-round [&_circle]:fill-current"
      >
        <path d={path} fill="none" strokeWidth="1.5" />
        <circle cx={W - PAD} cy={lastY} r="1.8" />
      </svg>
      {/* .spark-pct: 12px, tabular-nums mono; color inherited from parent .pos/.neg */}
      <span className={`spark-pct num ${cls} text-xs`}>
        {up ? "▲" : "▼"} {up ? "+" : "−"}
        {Math.abs(pct).toFixed(1)}%
      </span>
    </span>
  );
}
