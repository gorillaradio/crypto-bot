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
export type AgentEvent = { timestamp: string; kind: string; message: string };
export type Position = {
  symbol: string;
  quantity: string;
  avg_price: string;
  cost_basis: string;
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
