import { useEffect, useMemo, useState } from "react";
import {
  getAgents, getEquity, getEvents, getPositions, getMemory,
  type Agent, type EquityPoint, type AgentEvent, type Position, type AgentMemory,
} from "./api";
import { EquityChart } from "./components/EquityChart";
import { PositionsTable } from "./components/PositionsTable";
import { EventsFeed } from "./components/EventsFeed";
import { MemoryPanel } from "./components/MemoryPanel";
import { AgentFormModal } from "./components/AgentFormModal";
import { ConfirmDeleteModal } from "./components/ConfirmDeleteModal";

const usd = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;

function Return({ pct }: { pct: number }) {
  const up = pct >= 0;
  return (
    <span className={`num ${up ? "pos" : "neg"}`}>
      {up ? "▲" : "▼"} {up ? "+" : "−"}{Math.abs(pct).toFixed(2)}%
    </span>
  );
}

function elapsed(startIso: string): string {
  const ms = Date.now() - new Date(startIso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}g ${h % 24}h`;
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value num">{children}</div>
    </div>
  );
}

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [memory, setMemory] = useState<AgentMemory | null>(null);
  const [modal, setModal] = useState<"create" | "edit" | "delete" | null>(null);

  useEffect(() => {
    const load = () => getAgents().then(setAgents).catch(() => {});
    load();
    const h = setInterval(load, 15000);
    return () => clearInterval(h);
  }, []);

  useEffect(() => {
    if (selId == null && agents.length) setSelId(agents[0].id);
  }, [agents, selId]);

  useEffect(() => {
    if (selId == null) return;
    setMemory(null);
    const load = () => {
      getEquity(selId).then(setEquity).catch(() => {});
      getEvents(selId).then(setEvents).catch(() => {});
      getPositions(selId).then(setPositions).catch(() => {});
      getMemory(selId).then(setMemory).catch(() => {});
    };
    load();
    const h = setInterval(load, 15000);
    return () => clearInterval(h);
  }, [selId]);

  const reloadAgents = () => getAgents().then(setAgents).catch(() => {});

  const sel = useMemo(() => agents.find((a) => a.id === selId) ?? null, [agents, selId]);
  const equityNum = sel ? Number(sel.equity) : 0;
  const cashNum = sel ? Number(sel.cash_usd) : 0;
  const inPositions = Math.max(equityNum - cashNum, 0);

  return (
    <div className="app">
      <header className="topbar">
        <span className="logo">crypto<b>·</b>bot</span>
        <span className="live"><span className="dot" /> live</span>
      </header>

      <section className="agents-bar">
        {agents.map((a) => {
          const ret = Number(a.return_pct);
          return (
            <button
              key={a.id}
              className={`agent-tile${a.id === selId ? " sel" : ""}`}
              onClick={() => setSelId(a.id)}
            >
              <div className="name">{a.name}</div>
              <div className="eq num">{usd(Number(a.equity))}</div>
              <div className="ret"><Return pct={ret} /></div>
            </button>
          );
        })}
        <button className="agent-tile add" onClick={() => setModal("create")}>
          + nuovo agente
        </button>
      </section>

      {sel && (
        <>
          <section className="agent-header">
            <h1>{sel.name}</h1>
            {sel.instructions && <p className="instructions">{sel.instructions}</p>}
            <span className="meta">
              in corso da {elapsed(sel.duration_start)} · stato: {sel.status}
            </span>
            <div className="agent-actions">
              <button className="btn-ghost" onClick={() => setModal("edit")}>modifica</button>
              <button className="btn-ghost danger" onClick={() => setModal("delete")}>elimina</button>
            </div>
          </section>

          <section className="stats">
            <Stat label="Valore">{usd(equityNum)}</Stat>
            <Stat label="Rendimento"><Return pct={Number(sel.return_pct)} /></Stat>
            <Stat label="Cash">{usd(cashNum)}</Stat>
            <Stat label="In posizioni">{usd(inPositions)}</Stat>
            <Stat label="Posizioni">{positions.length}</Stat>
          </section>

          <section className="card chart-card">
            <div className="chart-head">
              <span className="pct"><Return pct={Number(sel.return_pct)} /></span>
              <span className="vs">equity vs investimento iniziale di $100</span>
            </div>
            <EquityChart data={equity} baseline={100} />
          </section>

          <div className="two-col">
            <section className="card">
              <h2>Posizioni</h2>
              <PositionsTable positions={positions} />
            </section>
            <section className="card">
              <h2>Attività</h2>
              <EventsFeed events={events} />
            </section>
          </div>

          <section className="card">
            <h2>Memoria</h2>
            {memory ? <MemoryPanel memory={memory} /> : <p className="empty">…</p>}
          </section>
        </>
      )}

      {modal === "create" && (
        <AgentFormModal
          mode="create"
          onClose={() => setModal(null)}
          onSaved={(a) => { setModal(null); reloadAgents(); setSelId(a.id); }}
        />
      )}
      {modal === "edit" && sel && (
        <AgentFormModal
          mode="edit"
          agent={sel}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); reloadAgents(); }}
        />
      )}
      {modal === "delete" && sel && (
        <ConfirmDeleteModal
          agent={sel}
          onClose={() => setModal(null)}
          onDeleted={(id) => {
            setModal(null);
            setSelId((cur) => (cur === id ? null : cur));
            reloadAgents();
          }}
        />
      )}
    </div>
  );
}
