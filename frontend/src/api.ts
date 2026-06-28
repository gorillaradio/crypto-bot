const BASE = import.meta.env.VITE_API_BASE ?? "";

export type EquityPoint = { timestamp: string; equity_usd: string };
export type AgentEvent = { timestamp: string; kind: string; message: string };
export type Agent = { id: number; name: string; status: string; cash_usd: string };

export async function getAgents(): Promise<Agent[]> {
  return (await fetch(`${BASE}/api/agents`)).json();
}
export async function getEquity(id: number): Promise<EquityPoint[]> {
  return (await fetch(`${BASE}/api/agents/${id}/equity`)).json();
}
export async function getEvents(id: number): Promise<AgentEvent[]> {
  return (await fetch(`${BASE}/api/agents/${id}/events`)).json();
}
