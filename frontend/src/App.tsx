import { useEffect, useMemo, useState } from "react";
import {
  getAgents, getEquity, getEvents, getPositions, getMemory,
  getMe, logout as apiLogout, exchangeViewerToken, AuthError,
  type Agent, type EquityPoint, type AgentEvent, type Position, type AgentMemory, type Role,
} from "./api";
import { Button } from "@/components/ui/button";
import { EquityChart } from "./components/EquityChart";
import { PositionsTable } from "./components/PositionsTable";
import { EventsFeed } from "./components/EventsFeed";
import { MemoryPanel } from "./components/MemoryPanel";
import { AgentFormModal } from "./components/AgentFormModal";
import { ConfirmDeleteModal } from "./components/ConfirmDeleteModal";
import { AgentSidebar } from "./components/AgentSidebar";
import { InstructionsBlock } from "./components/InstructionsBlock";
import { Login } from "./components/Login";
import { ShareLinksModal } from "./components/ShareLinksModal";

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

function Dashboard({ role, onAuthLost }: { role: "admin" | "viewer"; onAuthLost: () => void }) {
  const isAdmin = role === "admin";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [memory, setMemory] = useState<AgentMemory | null>(null);
  const [modal, setModal] = useState<"create" | "edit" | "delete" | "share" | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  // A 401 mid-session (e.g. a viewer's link was revoked) means the session is
  // gone — bounce back to the login screen instead of swallowing the error.
  const onErr = (e: unknown) => { if (e instanceof AuthError) onAuthLost(); };

  useEffect(() => {
    const load = () => getAgents().then(setAgents).catch(onErr);
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
      getEquity(selId).then(setEquity).catch(onErr);
      getEvents(selId).then(setEvents).catch(onErr);
      getPositions(selId).then(setPositions).catch(onErr);
      getMemory(selId).then(setMemory).catch(onErr);
    };
    load();
    const h = setInterval(load, 15000);
    return () => clearInterval(h);
  }, [selId]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  const reloadAgents = () => getAgents().then(setAgents).catch(onErr);
  const doLogout = async () => { await apiLogout().catch(() => {}); onAuthLost(); };

  const sel = useMemo(() => agents.find((a) => a.id === selId) ?? null, [agents, selId]);
  const equityNum = sel ? Number(sel.equity) : 0;
  const cashNum = sel ? Number(sel.cash_usd) : 0;
  const inPositions = Math.max(equityNum - cashNum, 0);

  const selectAgent = (id: number) => { setSelId(id); setNavOpen(false); };
  const openCreate = () => { setModal("create"); setNavOpen(false); };

  const sidebar = (
    <AgentSidebar
      agents={agents}
      selId={selId}
      onSelect={selectAgent}
      onCreate={isAdmin ? openCreate : undefined}
      onShare={isAdmin ? () => { setModal("share"); setNavOpen(false); } : undefined}
      onLogout={isAdmin ? doLogout : undefined}
    />
  );

  return (
    <div className="shell">
      <aside className="sidebar">{sidebar}</aside>

      <div
        className={`sheet-backdrop${navOpen ? " open" : ""}`}
        onClick={() => setNavOpen(false)}
        aria-hidden="true"
      />
      <div className={`sheet${navOpen ? " open" : ""}`} role="dialog" aria-label="Agenti" aria-modal="true">
        {sidebar}
      </div>

      <main className="main">
        <header className="mobile-bar">
          <button
            className="hamburger"
            onClick={() => setNavOpen(true)}
            aria-label="Apri elenco agenti"
            aria-expanded={navOpen}
          >
            <span /><span /><span />
          </button>
          <span className="logo">crypto<b>·</b>bot</span>
          <span className="live"><span className="dot" /> live</span>
        </header>

        {sel ? (
          <>
            <section className="agent-header">
              <div className="agent-title">
                <h1>{sel.name}</h1>
                {isAdmin && (
                  <div className="agent-actions">
                    <Button variant="outline" size="sm" onClick={() => setModal("edit")}>modifica</Button>
                    <Button variant="destructive" size="sm" onClick={() => setModal("delete")}>elimina</Button>
                  </div>
                )}
              </div>
              {sel.instructions && <InstructionsBlock text={sel.instructions} />}
              <span className="meta">
                in corso da {elapsed(sel.duration_start)} · stato: {sel.status}
              </span>
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
        ) : (
          <section className="card empty-state">
            <p className="empty">
              {isAdmin
                ? "Nessun agente ancora. Creane uno per iniziare l'esperimento."
                : "Nessun agente da mostrare."}
            </p>
            {isAdmin && (
              <Button onClick={() => setModal("create")}>+ nuovo agente</Button>
            )}
          </section>
        )}
      </main>

      {isAdmin && modal === "create" && (
        <AgentFormModal
          mode="create"
          onClose={() => setModal(null)}
          onSaved={(a) => { setModal(null); reloadAgents(); setSelId(a.id); }}
        />
      )}
      {isAdmin && modal === "edit" && sel && (
        <AgentFormModal
          mode="edit"
          agent={sel}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); reloadAgents(); }}
        />
      )}
      {isAdmin && modal === "delete" && sel && (
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
      {isAdmin && modal === "share" && (
        <ShareLinksModal onClose={() => setModal(null)} />
      )}
    </div>
  );
}

export default function App() {
  const [role, setRole] = useState<Role | "loading">("loading");

  const bootstrap = () => getMe().then((r) => setRole(r.role)).catch(() => setRole(null));

  useEffect(() => {
    const token = window.location.hash.slice(1);
    if (token) {
      exchangeViewerToken(token)
        .catch(() => {})
        .finally(() => {
          history.replaceState(null, "", window.location.pathname + window.location.search);
          bootstrap();
        });
    } else {
      bootstrap();
    }
  }, []);

  if (role === "loading") return <div className="login-screen" />;
  if (role === null) return <Login onAuthed={bootstrap} />;
  return <Dashboard role={role} onAuthLost={() => setRole(null)} />;
}
