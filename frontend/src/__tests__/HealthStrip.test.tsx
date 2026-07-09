import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { HealthStrip } from "../components/HealthStrip";
import type { AgentEvent } from "../api";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();

const dec = (ts: string, extra: object = {}): AgentEvent => ({
  timestamp: ts, kind: "decision", message: "", cycle_id: "c",
  payload: { status: "ok", note: "", executed: 0, skipped: [], skipped_count: 0,
             errors: 0, trigger: "schedule", wake_reason: null, ...extra },
});

describe("HealthStrip", () => {
  it("tutto a posto: riga muta senza ambra né rosso", () => {
    const { container } = render(
      <HealthStrip events={[dec(minutesAgo(3))]} decisionSeconds={3600} />);
    expect(screen.getByText(/ultimo ciclo/)).toBeInTheDocument();
    expect(screen.getByText(/riflessioni ok/)).toBeInTheDocument();
    expect(container.querySelector(".dot-warn")).toBeNull();
    expect(container.querySelector(".dot-err")).toBeNull();
  });

  it("degradi in ambra: saltate e riflessione scartata, coi motivi nel title", () => {
    const events: AgentEvent[] = [
      dec(minutesAgo(2), { skipped_count: 3,
        skipped: [{ type: "BUY", symbol: "DOGEUSDT", reason: "coin fuori universo" }] }),
      { timestamp: minutesAgo(5), kind: "reflection", message: "", cycle_id: "c",
        payload: { status: "invalid" } },
    ];
    const { container } = render(<HealthStrip events={events} decisionSeconds={3600} />);
    expect(screen.getByText(/3 saltate oggi/)).toBeInTheDocument();
    expect(screen.getByText(/1 riflessione scartata oggi/)).toBeInTheDocument();
    expect(screen.getByText(/3 saltate oggi/)).toHaveAttribute("title",
      expect.stringContaining("coin fuori universo"));
    expect(container.querySelectorAll(".dot-warn").length).toBeGreaterThan(0);
    expect(container.querySelector(".dot-err")).toBeNull();
  });

  it("rottura in rosso: loop fermo oltre l'intervallo atteso", () => {
    const { container } = render(
      <HealthStrip events={[dec(minutesAgo(120))]} decisionSeconds={3600} />);
    expect(screen.getByText(/loop fermo da/)).toBeInTheDocument();
    expect(container.querySelector(".dot-err")).not.toBeNull();
    expect(container.querySelector(".strip.is-broken")).not.toBeNull();
  });

  it("errori di esecuzione in rosso", () => {
    const { container } = render(
      <HealthStrip events={[dec(minutesAgo(1), { errors: 1 })]} decisionSeconds={3600} />);
    expect(screen.getByText(/1 errore/)).toBeInTheDocument();
    expect(container.querySelector(".dot-err")).not.toBeNull();
  });
});
