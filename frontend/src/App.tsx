import { useEffect, useMemo, useState } from "react";
import {
  getAgents, getEquity, getEvents, getPositions, getMemory,
  getMe, logout as apiLogout, exchangeViewerToken, AuthError,
  type Agent, type EquityPoint, type AgentEvent, type Position, type AgentMemory, type Role,
} from "./api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Sheet, SheetContent } from "@/components/ui/sheet";
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
    <Card className="min-w-0">
      <CardContent>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-1.5 text-2xl font-semibold leading-tight break-words min-w-0 overflow-hidden">{children}</div>
      </CardContent>
    </Card>
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

  // Manual Escape handler removed — shadcn Sheet handles Esc + backdrop dismiss natively.

  const reloadAgents = () => getAgents().then(setAgents).catch(onErr);
  const doLogout = async () => { await apiLogout().catch(() => {}); onAuthLost(); };

  const sel = useMemo(() => agents.find((a) => a.id === selId) ?? null, [agents, selId]);
  const equityNum = sel ? Number(sel.equity) : 0;
  const cashNum = sel ? Number(sel.cash_usd) : 0;
  const inPositions = Math.max(equityNum - cashNum, 0);

  const selectAgent = (id: number) => { setSelId(id); setNavOpen(false); };
  const openCreate = () => { setModal("create"); setNavOpen(false); };

  const sidebarContent = (
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
    // Shell: mobile-first single column; at lg+ the sidebar rail sits alongside content.
    <div className="lg:grid lg:grid-cols-[auto_1fr] min-h-svh">

      {/* Desktop persistent rail — hidden below lg */}
      <aside className="hidden lg:block w-64 sticky top-0 h-svh overflow-hidden bg-card border-r border-border">
        {sidebarContent}
      </aside>

      {/* Mobile drawer via shadcn Sheet — visible only below lg */}
      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent
          side="left"
          showCloseButton={false}
          className="p-0 w-72 max-w-none lg:hidden"
          aria-label="Agenti"
        >
          {sidebarContent}
        </SheetContent>
      </Sheet>

      {/* Main content area */}
      <main className="px-4 pt-4.5 pb-14 max-w-6xl lg:px-8 lg:pt-7 lg:pb-16">

        {/* Mobile top bar — hidden at lg+ */}
        <header className="flex items-center gap-3 pb-4 mb-4.5 border-b border-border lg:hidden">
          <button
            className="inline-flex flex-col justify-center gap-1 size-9.5 px-2.5 cursor-pointer bg-card border border-border rounded-lg"
            onClick={() => setNavOpen(true)}
            aria-label="Apri elenco agenti"
            aria-expanded={navOpen}
          >
            <span className="h-0.5 bg-foreground rounded-sm" />
            <span className="h-0.5 bg-foreground rounded-sm" />
            <span className="h-0.5 bg-foreground rounded-sm" />
          </button>
          <span className="font-bold tracking-[-0.02em] text-lg">crypto<b className="text-primary">·</b>bot</span>
          <span className="ml-auto inline-flex items-center gap-2 text-muted-foreground text-sm">
            <span className="live-dot" aria-hidden="true" />
            live
          </span>
        </header>

        {sel ? (
          <div className="space-y-5">
            <section className="pb-2">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold leading-tight">{sel.name}</h1>
                {isAdmin && (
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setModal("edit")}>modifica</Button>
                    <Button variant="destructive" size="sm" onClick={() => setModal("delete")}>elimina</Button>
                  </div>
                )}
              </div>
              {sel.instructions && <InstructionsBlock text={sel.instructions} />}
              <span className="text-xs text-muted-foreground mt-1 block">
                in corso da {elapsed(sel.duration_start)} · stato: {sel.status}
              </span>
            </section>

            <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <Stat label="Valore">{usd(equityNum)}</Stat>
              <Stat label="Rendimento"><Return pct={Number(sel.return_pct)} /></Stat>
              <Stat label="Cash">{usd(cashNum)}</Stat>
              <Stat label="In posizioni">{usd(inPositions)}</Stat>
              <Stat label="Posizioni">{positions.length}</Stat>
            </section>

            <Card>
              <CardContent>
                <div className="flex flex-wrap items-baseline gap-3 mb-3">
                  <span className="text-xl font-medium"><Return pct={Number(sel.return_pct)} /></span>
                  <span className="text-xs text-muted-foreground">equity vs investimento iniziale di $100</span>
                </div>
                <EquityChart data={equity} baseline={100} />
              </CardContent>
            </Card>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <Card>
                <CardContent>
                  <h2 className="text-sm font-semibold text-muted-foreground mb-3">Posizioni</h2>
                  <PositionsTable positions={positions} />
                </CardContent>
              </Card>
              <Card>
                <CardContent>
                  <h2 className="text-sm font-semibold text-muted-foreground mb-3">Attività</h2>
                  <EventsFeed events={events} />
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardContent>
                <h2 className="text-sm font-semibold text-muted-foreground mb-3">Memoria</h2>
                {memory ? <MemoryPanel memory={memory} /> : <p className="empty">…</p>}
              </CardContent>
            </Card>
          </div>
        ) : (
          <Card className="py-8">
            <CardContent className="flex flex-col items-start gap-3.5">
              <p className="text-muted-foreground text-sm">
                {isAdmin
                  ? "Nessun agente ancora. Creane uno per iniziare l'esperimento."
                  : "Nessun agente da mostrare."}
              </p>
              {isAdmin && (
                <Button onClick={() => setModal("create")}>+ nuovo agente</Button>
              )}
            </CardContent>
          </Card>
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
