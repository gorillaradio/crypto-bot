const BASE = import.meta.env.VITE_API_BASE ?? "";

export class AuthError extends Error {}
export type Role = "admin" | "viewer" | null;

export type Agent = {
  id: number;
  name: string;
  status: string;
  instructions: string;
  cash_usd: string;
  equity: string;
  return_pct: string;
  duration_start: string;
  duration_end: string;
  decision_seconds: number;
};
export type EquityPoint = { timestamp: string; equity_usd: string };
export type BenchmarkPoint = { kind: string; timestamp: string; equity_usd: string };
export type BenchmarkMetric = { return_pct: string; max_drawdown_pct: string; sharpe: string };
// Finestra di scoring: il label ("24h", "7d", …) arriva dalla config del backend
export type WindowHitRate = { window: string; hit_rate: string | null };
export type AgentMetrics = {
  return_pct: string; max_drawdown_pct: string; sharpe: string;
  hit_rates: WindowHitRate[];
  benchmarks: Record<string, BenchmarkMetric>;
};
export type ModelMetrics = {
  model_name: string | null; n_scored_actions: number;
  hit_rates: WindowHitRate[];
};
export type PositionSummary = {
  opened_at: string | null; closed_at: string; held_minutes: number | null;
  invested_usd: string | null; realized_total_usd: string; realized_total_pct: string | null;
};
export type TradePayload = {
  side: "BUY" | "SELL"; symbol: string; qty: string; price: string; fee: string;
  usd_value?: string; rationale?: string | null;
  position?: "new" | "increase";                       // solo BUY
  fraction?: string; avg_cost?: string;                // solo SELL
  realized_pnl_pct?: string; realized_pnl_usd?: string; // solo SELL (eventi nuovi)
  position_summary?: PositionSummary;                  // solo SELL a chiusura totale
};
export type SkippedAction = { type: string; symbol?: string | null; reason: string };
export type DecisionPayload = {
  status: "ok" | "error"; note?: string; executed?: number;
  skipped?: SkippedAction[]; skipped_count?: number; errors?: number;
  trigger?: string | null; wake_reason?: string | null; detail?: string;
};
export type ReflectionPayload = { status: "ok" | "invalid" | "error"; distilled?: string; detail?: string };
export type RawPayload = { raw: string; folded?: boolean };
export type EventPayload = TradePayload | DecisionPayload | ReflectionPayload | RawPayload;

export type AgentEvent = {
  timestamp: string; kind: string; message: string;
  payload?: EventPayload | null; cycle_id: string | null;
};
export type Position = {
  symbol: string;
  quantity: string;
  avg_price: string;
  cost_basis: string;
  last_price: string | null;
  unrealized_pnl_pct: string | null;
  market_value: string | null;
  opened_at: string | null;
  realized_usd: string;
};
export type LifecycleEvaluation = {
  action: string; rationale: string | null; cycle_id: string | null; timestamp: string;
};
export type OpenLifecycle = {
  lifecycle_id: string;
  cycle_id: string | null;
  symbol: string;
  status: "open";
  opened_at: string;
  last_changed_at: string;
  quantity: string;
  avg_price: string;
  cost_basis: string;
  last_price: string | null;
  exposure_usd: string | null;
  fees_usd: string;
  realized_usd: string;
  unrealized_usd: string | null;
  net_result_usd: string | null;
  net_result_pct: string | null;
  evaluation: LifecycleEvaluation | null;
};
export type LifecycleState = "open" | "closed" | "all";
export type LifecycleSummary = {
  lifecycle_id: string;
  symbol: string;
  status: "open" | "closed";
  opened_at: string;
  closed_at: string | null;
  last_changed_at: string;
  quantity: string | null;
  exposure_usd: string | null;
  portfolio_weight_pct: string | null;
  held_minutes: number | null;
  invested_usd: string;
  fees_usd: string;
  net_result_usd: string | null;
  net_result_pct: string | null;
  market_series_24h: string[] | null;
};
export type LifecyclePage = { items: LifecycleSummary[]; next_cursor: string | null };
export type ClosedPosition = {
  symbol: string; opened_at: string | null; closed_at: string; held_minutes: number | null;
  invested_usd: string | null; realized_total_usd: string; realized_total_pct: string | null;
  close_cycle_id: string | null;
};
export type Trade = {
  id: number;
  symbol: string;
  side: string; // "BUY" | "SELL"
  quantity: string;
  price: string;
  fee: string;
  timestamp: string;
};
export type PolicyLine = { ref: string; content: string };
export type AgentMemory = {
  coin_theses: string;
  trade_lessons: string;
  strategy_notes: string;
  self_policy: PolicyLine[];
  caps: Record<string, number>;
};
export type MemoryEntry = {
  section: string; content: string; cycle_id: string | null; active: boolean; created_at: string;
};
export type PromptPair = { system: string; user: string; note?: string | null };
export type PromptPreview = { decision: PromptPair; reflection: PromptPair; retry: PromptPair };
export type Decision = {
  id: number;
  cycle_id: string;
  kind: string;
  trigger: string;
  parsed_output: string | null;
  parse_status: string;
  model_name: string | null;
  latency_ms: number;
  created_at: string;
};
export type Observation = {
  source: string;
  title: string;
  url: string | null;
  published_at: string;
  symbols: string[];
};
export type Highlight = { symbol: string; snapshot: string; signal: string; note: string };
export type MarketBrief = { regime: string; highlights: Highlight[]; key_news: string[]; as_of: string | null };

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (r.status === 401) throw new AuthError();
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const getAgents = () => get<Agent[]>("/api/agents");
export const getEquity = (id: number) => get<EquityPoint[]>(`/api/agents/${id}/equity`);
export const getBenchmarks = (id: number) => get<BenchmarkPoint[]>(`/api/agents/${id}/benchmarks`);
export const getAgentMetrics = (id: number) => get<AgentMetrics>(`/api/agents/${id}/metrics`);
export const getModelMetrics = () => get<ModelMetrics[]>("/api/metrics/by-model");
export const getEvents = (id: number) => get<AgentEvent[]>(`/api/agents/${id}/events`);
export const getTrades = (id: number) => get<Trade[]>(`/api/agents/${id}/trades`);
export const getPositions = (id: number) => get<Position[]>(`/api/agents/${id}/positions`);
export const getOpenLifecycles = (id: number) =>
  get<OpenLifecycle[]>(`/api/agents/${id}/lifecycles/open`);
export function getLifecycles(
  id: number,
  options: { state: LifecycleState; closedSince?: string; limit: number; cursor?: string },
) {
  const query = new URLSearchParams({ state: options.state, limit: String(options.limit) });
  if (options.closedSince) query.set("closed_since", options.closedSince);
  if (options.cursor) query.set("cursor", options.cursor);
  return get<LifecyclePage>(`/api/agents/${id}/lifecycles?${query}`);
}
export const getClosedPositions = (id: number) => get<ClosedPosition[]>(`/api/agents/${id}/positions/closed`);
export const getMemory = (id: number) => get<AgentMemory>(`/api/agents/${id}/memory`);
export const getMemoryJournal = (id: number) => get<MemoryEntry[]>(`/api/agents/${id}/memory/journal`);
export const getPrompt = (id: number) => get<PromptPreview>(`/api/agents/${id}/prompt`);
export const getDecisions = (id: number) => get<Decision[]>(`/api/agents/${id}/decisions`);
export const getObservations = () => get<Observation[]>("/api/observations");
export const getBrief = (id: number) => get<MarketBrief | null>(`/api/agents/${id}/brief`);

export type AgentCreateInput = {
  name: string;
  instructions: string;
  duration_days: number;
  model_name: string;
  universe: "TOP_50" | "TOP_100";
  stop_loss: number | null;
  take_profit: number | null;
};

async function mutate<T>(path: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) throw new AuthError();
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const createAgent = (input: AgentCreateInput) =>
  mutate<Agent>("/api/agents", "POST", input);
export const updateAgent = (id: number, input: { name: string }) =>
  mutate<Agent>(`/api/agents/${id}`, "PATCH", input);
export const deleteAgent = (id: number) =>
  mutate<void>(`/api/agents/${id}`, "DELETE");

export const getMe = () => get<{ role: Role }>("/api/auth/me");
export const login = (password: string) =>
  mutate<{ role: Role }>("/api/auth/login", "POST", { password });
export const logout = () => mutate<void>("/api/auth/logout", "POST");
export const exchangeViewerToken = (token: string) =>
  mutate<{ role: Role }>("/api/auth/viewer", "POST", { token });

export type ShareLink = {
  id: number; label: string | null; token: string; url: string; created_at: string;
};
export const listShareLinks = () => get<ShareLink[]>("/api/share-links");
export const createShareLink = (label?: string) =>
  mutate<ShareLink>("/api/share-links", "POST", { label: label ?? null });
export const revokeShareLink = (id: number) =>
  mutate<void>(`/api/share-links/${id}`, "DELETE");
