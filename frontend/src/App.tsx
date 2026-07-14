import { useEffect, useMemo, useRef, useState } from "react";
import {
  getAgents, getEquity, getEvents, getTrades, getLifecycles, getMemory, getMemoryJournal, getDecisions,
  getMe, logout as apiLogout, exchangeViewerToken, AuthError,
  getBenchmarks, getAgentMetrics, getModelMetrics, getObservations,
  type Agent, type EquityPoint, type AgentEvent, type Trade, type LifecycleMarket, type LifecycleState, type LifecycleSummary, type AgentMemory, type Role,
  type BenchmarkPoint, type AgentMetrics, type ModelMetrics, type MemoryEntry, type Decision,
  type Observation,
} from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { BenchmarkChart } from "./components/BenchmarkChart";
import { MetricsPanel } from "./components/MetricsPanel";
import { ModelMetricsPanel } from "./components/ModelMetricsPanel";
import { PositionsTable } from "./components/PositionsTable";
import { TradesTable } from "./components/TradesTable";
import { EventsFeed } from "./components/EventsFeed";
import { HealthStrip } from "./components/HealthStrip";
import { MemoryPanel } from "./components/MemoryPanel";
import { DecisionsPanel } from "./components/DecisionsPanel";
import { ObservationsFeed } from "./components/ObservationsFeed";
import { PromptPanel } from "./components/PromptPanel";
import { MarketBriefPanel } from "./components/MarketBriefPanel";
import { AgentFormModal } from "./components/AgentFormModal";
import { ConfirmDeleteModal } from "./components/ConfirmDeleteModal";
import { AgentSidebar } from "./components/AgentSidebar";
import { InstructionsBlock } from "./components/InstructionsBlock";
import { Login } from "./components/Login";
import { ShareLinksModal } from "./components/ShareLinksModal";

const usd = (n: number) => `$${n.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
const unavailableMarket: LifecycleMarket = { status: "unavailable", as_of: null };

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

// Intestazione condivisa delle card: titolo + una riga che dice cosa si sta guardando.
function PanelHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <h2 className="text-sm font-semibold">{title}</h2>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Dashboard({ role, onAuthLost }: { role: "admin" | "viewer"; onAuthLost: () => void }) {
  const isAdmin = role === "admin";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkPoint[]>([]);
  const [metrics, setMetrics] = useState<AgentMetrics | null>(null);
  const [modelMetrics, setModelMetrics] = useState<ModelMetrics[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [positions, setPositions] = useState<LifecycleSummary[]>([]);
  const [positionMarket, setPositionMarket] = useState<LifecycleMarket>(unavailableMarket);
  const [positionState, setPositionState] = useState<LifecycleState>("open");
  const [closedSince, setClosedSince] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() - 7);
    return date.toISOString().slice(0, 10);
  });
  const [allHistory, setAllHistory] = useState(false);
  const [positionCursor, setPositionCursor] = useState<string | null>(null);
  const [positionsLoadingMore, setPositionsLoadingMore] = useState(false);
  const lifecycleRequest = useRef(0);
  const lifecycleFetch = useRef(0);
  const lifecycleLoadMorePending = useRef(false);
  const lifecyclePaginationExpanded = useRef(false);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [memory, setMemory] = useState<AgentMemory | null>(null);
  const [journalEntries, setJournalEntries] = useState<MemoryEntry[]>([]);
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

  // Global, not per-agent — fetched once on mount.
  useEffect(() => {
    getModelMetrics().then(setModelMetrics).catch(onErr);
  }, []);

  useEffect(() => {
    if (selId == null && agents.length) setSelId(agents[0].id);
  }, [agents, selId]);

  useEffect(() => {
    if (selId == null) return;
    setMemory(null);
    setJournalEntries([]);
    setTrades([]);
    const load = () => {
      getEquity(selId).then(setEquity).catch(onErr);
      getBenchmarks(selId).then(setBenchmarks).catch(onErr);
      getAgentMetrics(selId).then(setMetrics).catch(onErr);
      getEvents(selId).then(setEvents).catch(onErr);
      getTrades(selId).then(setTrades).catch(onErr);
      getDecisions(selId).then(setDecisions).catch(onErr);
      getMemory(selId).then(setMemory).catch(onErr);
      getMemoryJournal(selId).then(setJournalEntries).catch(onErr);
      getObservations().then(setObservations).catch(onErr);
    };
    load();
    const h = setInterval(load, 15000);
    return () => clearInterval(h);
  }, [selId]);

  const lifecycleOptions = useMemo(() => ({
    state: positionState,
    limit: 50,
    ...(positionState !== "open"
      ? { closedSince: allHistory ? "1970-01-01T00:00:00.000Z" : `${closedSince}T00:00:00.000Z` }
      : {}),
  }), [positionState, allHistory, closedSince]);

  useEffect(() => {
    if (selId == null) return;
    const request = ++lifecycleRequest.current;
    lifecyclePaginationExpanded.current = false;
    lifecycleLoadMorePending.current = false;
    setPositionsLoadingMore(false);
    setPositions([]);
    setPositionMarket(unavailableMarket);
    setPositionCursor(null);
    const load = () => {
      const fetch = ++lifecycleFetch.current;
      return getLifecycles(selId, lifecycleOptions)
      .then((page) => {
        if (lifecycleRequest.current !== request || lifecycleFetch.current !== fetch) return;
        setPositions(page.items);
        setPositionMarket(page.market);
        setPositionCursor(page.next_cursor);
      })
      .catch(onErr);
    };
    load();
    const h = setInterval(() => {
      if (!lifecyclePaginationExpanded.current) load();
    }, 15000);
    return () => clearInterval(h);
  }, [selId, lifecycleOptions]);

  const loadMorePositions = () => {
    if (selId == null || positionCursor == null || lifecycleLoadMorePending.current) return;
    const request = lifecycleRequest.current;
    const fetch = ++lifecycleFetch.current;
    lifecycleLoadMorePending.current = true;
    lifecyclePaginationExpanded.current = true;
    setPositionsLoadingMore(true);
    getLifecycles(selId, { ...lifecycleOptions, cursor: positionCursor })
      .then((page) => {
        if (lifecycleRequest.current !== request || lifecycleFetch.current !== fetch) return;
        setPositions((current) => {
          const byId = new Map(current.map((item) => [item.lifecycle_id, item]));
          for (const item of page.items) byId.set(item.lifecycle_id, item);
          return [...byId.values()];
        });
        setPositionMarket(page.market);
        setPositionCursor(page.next_cursor);
      })
      .catch((error) => {
        if (lifecycleRequest.current === request && lifecycleFetch.current === fetch)
          lifecyclePaginationExpanded.current = false;
        onErr(error);
      })
      .finally(() => {
        if (lifecycleRequest.current === request) {
          lifecycleLoadMorePending.current = false;
          setPositionsLoadingMore(false);
        }
      });
  };

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

            <HealthStrip events={events} decisionSeconds={sel.decision_seconds} />

            <Card>
              <CardContent>
                <div className="flex flex-wrap items-baseline gap-3 mb-3">
                  <span className="text-xl font-medium"><Return pct={Number(sel.return_pct)} /></span>
                  <span className="text-xs text-muted-foreground">agente vs benchmark · base $100</span>
                </div>
                <BenchmarkChart equity={equity} benchmarks={benchmarks} />
                <MetricsPanel metrics={metrics} />
                <h3 className="text-sm font-medium mt-4 mb-2">Hit-rate per modello</h3>
                <ModelMetricsPanel models={modelMetrics} />
              </CardContent>
            </Card>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <Card>
                <CardContent>
                  <PanelHead title="Posizioni" hint="vite aperte e chiuse, confrontate con gli stessi criteri" />
                  <div className="mb-3 flex flex-wrap items-center gap-3">
                    <div className="seg" role="group" aria-label="Filtra le posizioni">
                      {(["open", "closed", "all"] as const).map((state) => (
                        <button key={state} type="button" aria-pressed={positionState === state} onClick={() => setPositionState(state)}>
                          {{ open: "Aperte", closed: "Chiuse", all: "Tutte" }[state]}
                        </button>
                      ))}
                    </div>
                    {positionState !== "open" && (
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <label htmlFor="closed-since">Dal</label>
                        <Input id="closed-since" type="date" value={closedSince} disabled={allHistory} required onChange={(e) => { if (e.target.value) setClosedSince(e.target.value); }} className="h-8 w-auto text-xs" />
                        <label className="flex items-center gap-1.5"><input type="checkbox" checked={allHistory} onChange={(e) => setAllHistory(e.target.checked)} /> Tutto lo storico</label>
                      </div>
                    )}
                  </div>
                  <PositionsTable items={positions} market={positionMarket} state={positionState} />
                  {positionCursor && <Button variant="outline" size="sm" className="mt-3" disabled={positionsLoadingMore} onClick={loadMorePositions}>{positionsLoadingMore ? "Caricamento…" : "Carica altro"}</Button>}
                </CardContent>
              </Card>
              <Card>
                <CardContent>
                  <PanelHead title="Operazioni" hint="tutti gli acquisti e le vendite eseguiti" />
                  <TradesTable trades={trades} />
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardContent>
                <PanelHead title="Attività" hint="il diario delle decisioni: cosa ha fatto e perché" />
                <EventsFeed events={events} policy={memory?.self_policy ?? []} />
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <PanelHead title="Memoria" hint="cosa ha imparato e le regole che si è dato" />
                <MemoryPanel memory={memory} entries={journalEntries} />
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <PanelHead title="Decisioni" hint="telemetria delle chiamate al modello" />
                <DecisionsPanel decisions={decisions} />
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <PanelHead title="Osservazioni" hint="le news che arrivano agli agenti" />
                <ObservationsFeed observations={observations} />
              </CardContent>
            </Card>

            {selId !== null && sel && (
              <Card>
                <CardContent>
                  <PanelHead title="Market brief" hint="la sintesi di mercato dell'analista, condivisa da tutti" />
                  <MarketBriefPanel agentId={selId} />
                </CardContent>
              </Card>
            )}

            {selId !== null && (
              <Card>
                <CardContent>
                  <PanelHead title="Prompt" hint="i testi inviati all'LLM, così come li vede" />
                  <PromptPanel agentId={selId} />
                </CardContent>
              </Card>
            )}
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
