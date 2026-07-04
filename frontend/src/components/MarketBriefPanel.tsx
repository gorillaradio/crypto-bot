import { useEffect, useState } from "react";
import { getBrief, type MarketBrief } from "../api";

const signalMark = (s: string) => (s === "bullish" ? "🟢" : s === "bearish" ? "🔴" : "⚪");

export function BriefView({ brief }: { brief: MarketBrief }) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Regime</span>
        <p className="text-sm">{brief.regime || "—"}</p>
      </div>
      {brief.highlights.length > 0 && (
        <ul className="flex flex-col gap-1">
          {brief.highlights.map((h) => (
            <li key={h.symbol} className="text-sm">
              <span className="mr-1">{signalMark(h.signal)}</span>
              <span className="font-medium">{h.symbol.replace(/USDT$/, "")}</span>
              {h.note && <span className="text-muted-foreground"> — {h.note}</span>}
            </li>
          ))}
        </ul>
      )}
      {brief.key_news.length > 0 && (
        <ul className="flex flex-col gap-0.5 list-disc pl-4">
          {brief.key_news.map((n, i) => (
            <li key={i} className="text-xs text-muted-foreground">{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MarketBriefPanel({ agentId, brainVersion }: { agentId: number; brainVersion: string }) {
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  useEffect(() => {
    let alive = true;
    setState("loading");
    getBrief(agentId)
      .then((b) => { if (alive) { setBrief(b); setState("ready"); } })
      .catch(() => { if (alive) setState("error"); });
    return () => { alive = false; };
  }, [agentId]);

  return (
    <div className="flex flex-col gap-2">
      {brainVersion !== "v2" && (
        <p className="text-xs text-muted-foreground">
          Questo agente usa il brain v1 (monolitico) e non consuma il market brief.
        </p>
      )}
      {state === "loading" && <p className="text-sm text-muted-foreground">Carico il brief…</p>}
      {state === "error" && <p className="text-sm text-muted-foreground">Brief non disponibile.</p>}
      {state === "ready" && (brief
        ? <BriefView brief={brief} />
        : <p className="text-sm text-muted-foreground">Nessun brief ancora generato.</p>)}
    </div>
  );
}
