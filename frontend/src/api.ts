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
export type AgentEvent = { timestamp: string; kind: string; message: string; cycle_id: string | null };
export type Position = {
  symbol: string;
  quantity: string;
  avg_price: string;
  cost_basis: string;
};
export type AgentMemory = {
  coin_theses: string;
  trade_lessons: string;
  strategy_notes: string;
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
export const getEvents = (id: number) => get<AgentEvent[]>(`/api/agents/${id}/events`);
export const getPositions = (id: number) => get<Position[]>(`/api/agents/${id}/positions`);
export const getMemory = (id: number) => get<AgentMemory>(`/api/agents/${id}/memory`);
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
