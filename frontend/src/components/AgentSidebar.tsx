import type { Agent } from "../api";
import { Button } from "@/components/ui/button";

const usd = (n: number) =>
  `$${n.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;

function Ret({ pct }: { pct: number }) {
  const up = pct >= 0;
  return (
    <span className={`num ${up ? "pos" : "neg"}`}>
      {up ? "▲" : "▼"} {up ? "+" : "−"}
      {Math.abs(pct).toFixed(2)}%
    </span>
  );
}

type Props = {
  agents: Agent[];
  selId: number | null;
  onSelect: (id: number) => void;
  onCreate?: () => void;
  onShare?: () => void;
  onLogout?: () => void;
};

// Agent switcher + at-a-glance leaderboard. Same component drives the persistent
// desktop rail and the mobile sheet; ranked by equity so "chi sta vincendo" reads
// instantly (a core PRODUCT.md principle).
export function AgentSidebar({ agents, selId, onSelect, onCreate, onShare, onLogout }: Props) {
  const ranked = [...agents].sort((a, b) => Number(b.equity) - Number(a.equity));

  return (
    <nav
      className="flex flex-col h-full"
      aria-label="Agenti"
    >
      {/* rail-head: logo + live indicator */}
      <div className="flex items-center justify-between px-[16px] pt-[18px] pb-[16px] border-b border-border">
        <span className="font-bold tracking-[-0.02em] text-[18px]">
          crypto<b className="text-primary">·</b>bot
        </span>
        {/* live dot — pulse animation defined in index.css */}
        <span className="inline-flex items-center gap-[7px] text-muted-foreground text-[13px]">
          <span className="live-dot" aria-hidden="true" />
          live
        </span>
      </div>

      {/* rail-list: scrollable agent list */}
      <div
        className="flex-1 min-h-0 overflow-y-auto py-[12px] px-[10px] flex flex-col gap-[3px]"
        role="list"
      >
        {ranked.map((a, i) => {
          const sel = a.id === selId;
          return (
            <button
              key={a.id}
              role="listitem"
              className={[
                // grid: rank col (16px) | body | equity
                "grid grid-cols-[16px_1fr_auto] items-center gap-[10px]",
                "w-full text-left font-[inherit] text-foreground",
                "bg-transparent border border-transparent rounded-[8px]",
                "px-[10px] py-[9px] cursor-pointer",
                "transition-[background,border-color] duration-[150ms] ease-[ease]",
                sel
                  ? "bg-card border-border"
                  : "hover:bg-card",
              ].join(" ")}
              onClick={() => onSelect(a.id)}
              aria-current={sel ? "true" : undefined}
            >
              {/* rank number */}
              <span
                className={[
                  "num text-[12px] text-center",
                  sel ? "text-primary" : "text-muted-foreground/80",
                ].join(" ")}
              >
                {i + 1}
              </span>

              {/* name + return */}
              <span className="flex flex-col gap-[2px] min-w-0">
                <span className="rail-name font-semibold text-[14px] whitespace-nowrap overflow-hidden text-ellipsis">
                  {a.name}
                </span>
                <span className="text-[12px]">
                  <Ret pct={Number(a.return_pct)} />
                </span>
              </span>

              {/* equity */}
              <span className="num text-[13px] text-muted-foreground">
                {usd(Number(a.equity))}
              </span>
            </button>
          );
        })}
      </div>

      {/* add button — admin only */}
      {onCreate && (
        <button
          className={[
            "mx-[12px] mb-[14px] p-[10px] rounded-[8px]",
            "bg-transparent border border-dashed border-border text-muted-foreground",
            "font-[inherit] cursor-pointer",
            "transition-[border-color,color] duration-[150ms] ease-[ease]",
            "hover:border-muted-foreground hover:text-foreground",
          ].join(" ")}
          onClick={onCreate}
        >
          <span aria-hidden="true">+</span> nuovo agente
        </button>
      )}

      {/* footer — admin only: share + logout */}
      {(onShare || onLogout) && (
        <div className="mt-auto pt-[12px] border-t border-border flex gap-[8px] px-[10px] pb-[10px]">
          {onShare && (
            <Button variant="outline" size="sm" onClick={onShare}>
              Condividi
            </Button>
          )}
          {onLogout && (
            <Button variant="outline" size="sm" onClick={onLogout}>
              Esci
            </Button>
          )}
        </div>
      )}
    </nav>
  );
}
