import type { Agent } from "../api";

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
  onCreate: () => void;
};

// Agent switcher + at-a-glance leaderboard. Same component drives the persistent
// desktop rail and the mobile sheet; ranked by equity so "chi sta vincendo" reads
// instantly (a core PRODUCT.md principle).
export function AgentSidebar({ agents, selId, onSelect, onCreate }: Props) {
  const ranked = [...agents].sort((a, b) => Number(b.equity) - Number(a.equity));

  return (
    <nav className="rail" aria-label="Agenti">
      <div className="rail-head">
        <span className="logo">
          crypto<b>·</b>bot
        </span>
        <span className="live">
          <span className="dot" /> live
        </span>
      </div>

      <div className="rail-list" role="list">
        {ranked.map((a, i) => {
          const sel = a.id === selId;
          return (
            <button
              key={a.id}
              role="listitem"
              className={`rail-item${sel ? " sel" : ""}`}
              onClick={() => onSelect(a.id)}
              aria-current={sel ? "true" : undefined}
            >
              <span className="rail-rank num">{i + 1}</span>
              <span className="rail-body">
                <span className="rail-name">{a.name}</span>
                <span className="rail-ret">
                  <Ret pct={Number(a.return_pct)} />
                </span>
              </span>
              <span className="rail-eq num">{usd(Number(a.equity))}</span>
            </button>
          );
        })}
      </div>

      <button className="rail-add" onClick={onCreate}>
        <span aria-hidden="true">+</span> nuovo agente
      </button>
    </nav>
  );
}
