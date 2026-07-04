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
};
export type EquityPoint = { timestamp: string; equity_usd: string };
export type BenchmarkPoint = { kind: string; timestamp: string; equity_usd: string };
export type BenchmarkMetric = { return_pct: string; max_drawdown_pct: string; sharpe: string };
export type AgentMetrics = {
  return_pct: string; max_drawdown_pct: string; sharpe: string;
  hit_rate_24h: string | null; hit_rate_7d: string | null;
  benchmarks: Record<string, BenchmarkMetric>;
};
export type ModelMetrics = {
  model_name: string | null; n_scored_actions: number;
  hit_rate_24h: string | null; hit_rate_7d: string | null;
};
export type AgentEvent = { timestamp: string; kind: string; message: string; cycle_id: string | null };
export type Position = {
  symbol: string;
  quantity: string;
  avg_price: string;
  cost_basis: string;
  last_price: string | null;
  unrealized_pnl_pct: string | null;
  market_value: string | null;
};
export type AgentMemory = {
  coin_theses: string;
  trade_lessons: string;
  strategy_notes: string;
};
export type MemoryEntry = {
  section: string; content: string; cycle_id: string | null; active: boolean; created_at: string;
};
export type PromptPair = { system: string; user: string; note?: string | null };
export type PromptPreview = { decision: PromptPair; reflection: PromptPair; retry: PromptPair };

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
export const getPositions = (id: number) => get<Position[]>(`/api/agents/${id}/positions`);
export const getMemory = (id: number) => get<AgentMemory>(`/api/agents/${id}/memory`);
export const getMemoryJournal = (id: number) => get<MemoryEntry[]>(`/api/agents/${id}/memory/journal`);
export const getPrompt = (id: number) => get<PromptPreview>(`/api/agents/${id}/prompt`);

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

// Recent hourly closes for a coin's sparkline — fetched straight from Binance's
// public, CORS-enabled klines endpoint (no backend involvement). Cached briefly
// so the 15s dashboard poll doesn't hammer it.
const klineCache = new Map<string, { ts: number; closes: number[] }>();
const KLINE_TTL = 5 * 60 * 1000;

export async function getKlines(symbol: string, hours = 24): Promise<number[]> {
  const cached = klineCache.get(symbol);
  if (cached && Date.now() - cached.ts < KLINE_TTL) return cached.closes;
  const url = `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=1h&limit=${hours}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`klines ${symbol} → ${r.status}`);
  const rows: unknown[][] = await r.json();
  const closes = rows.map((row) => Number(row[4])); // index 4 = close
  klineCache.set(symbol, { ts: Date.now(), closes });
  return closes;
}

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
