import { useEffect, useState } from "react";
import { getAgents, getEquity, getEvents, type Agent, type EquityPoint, type AgentEvent } from "./api";
import { EquityChart } from "./components/EquityChart";
import { PositionsTable } from "./components/PositionsTable";
import { EventsFeed } from "./components/EventsFeed";

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);

  useEffect(() => { getAgents().then(setAgents); }, []);
  useEffect(() => {
    if (!agents.length) return;
    const id = agents[0].id;
    const tick = () => { getEquity(id).then(setEquity); getEvents(id).then(setEvents); };
    tick();
    const h = setInterval(tick, 30000);
    return () => clearInterval(h);
  }, [agents]);

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto" }}>
      <h1>crypto-bot</h1>
      {agents[0] && <PositionsTable cash={agents[0].cash_usd} />}
      <EquityChart data={equity} />
      <h3>Eventi</h3>
      <EventsFeed events={events} />
    </main>
  );
}
