const BASE = import.meta.env.VITE_API_BASE ?? "";

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

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const getAgents = () => get<Agent[]>("/api/agents");
export const getEquity = (id: number) => get<EquityPoint[]>(`/api/agents/${id}/equity`);
export const getEvents = (id: number) => get<AgentEvent[]>(`/api/agents/${id}/events`);
export const getPositions = (id: number) => get<Position[]>(`/api/agents/${id}/positions`);
export const getMemory = (id: number) => get<AgentMemory>(`/api/agents/${id}/memory`);

export type AgentCreateInput = {
  name: string;
  instructions: string;
  duration_days: number;
  model_provider: "anthropic" | "deepseek" | "glm" | "openrouter";
  model_name: string;
  universe: "TOP_50" | "TOP_100";
};

async function mutate<T>(path: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const createAgent = (input: AgentCreateInput) =>
  mutate<Agent>("/api/agents", "POST", input);
export const updateAgent = (id: number, input: { name: string }) =>
  mutate<Agent>(`/api/agents/${id}`, "PATCH", input);
export const deleteAgent = (id: number) =>
  mutate<void>(`/api/agents/${id}`, "DELETE");
