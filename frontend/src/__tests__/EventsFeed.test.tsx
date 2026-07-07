import { render, screen, within, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EventsFeed } from "../components/EventsFeed";
import type { AgentEvent } from "../api";

const ev = (
  kind: string, message: string, cycle_id: string | null,
  timestamp = "2026-06-29T09:40:39Z",
): AgentEvent => ({ timestamp, kind, message, cycle_id });

describe("EventsFeed", () => {
  it("renders a cycle as one diary block: note headline, trade with its why, memory chip", () => {
    // API order is desc: reflection, decision, then reasoning/trade.
    const events = [
      ev("reflection", "memoria aggiornata dopo trade chiuso", "c1"),
      ev("decision", "ciclo decisione (LLM): trim AEVO, add ACT — 1 operazioni, 0 saltate, 0 errori", "c1"),
      ev("reasoning", "ACT momentum continues, adding", "c1"),
      ev("trade", "BUY 378 ACTUSDT @ $0.0132 (fee $0.005)", "c1"),
    ];
    const { container } = render(<EventsFeed events={events} />);

    expect(container.querySelectorAll(".cycle")).toHaveLength(1);

    // the agent's note is the headline; the raw prefix and the counts are lifted out
    const head = container.querySelector(".cycle-head")!;
    expect(head.textContent).toContain("trim AEVO, add ACT");
    expect(head.textContent).not.toContain("ciclo decisione");
    expect(head.textContent).not.toContain("errori");

    // the trade line is structured and carries its own rationale
    const move = container.querySelector(".move")! as HTMLElement;
    expect(within(move).getByText("BUY")).toBeInTheDocument();
    expect(move.textContent).toContain("ACT");
    expect(move.textContent).toContain("378 @ $0.0132");
    expect(move.textContent).toContain("ACT momentum continues");

    expect(screen.getByText(/memoria aggiornata/)).toBeInTheDocument();
  });

  it("summarizes cycles and trades in the header bar", () => {
    const events = [
      ev("decision", "ciclo decisione (LLM): hold — 0 operazioni, 0 saltate, 0 errori", "c2"),
      ev("decision", "ciclo decisione (LLM): compro ACT — 1 operazioni, 0 saltate, 0 errori", "c1"),
      ev("trade", "BUY 1 ACTUSDT @ $1 (fee $0.001)", "c1"),
    ];
    render(<EventsFeed events={events} />);
    expect(screen.getByText(/2 cicli/)).toBeInTheDocument();
    expect(screen.getByText(/1 operazione/)).toBeInTheDocument();
  });

  it("filters hold-only cycles out with 'solo operazioni'", () => {
    const events = [
      ev("decision", "ciclo decisione (LLM): hold — 0 operazioni, 0 saltate, 0 errori", "c2"),
      ev("decision", "ciclo decisione (LLM): compro ACT — 1 operazioni, 0 saltate, 0 errori", "c1"),
      ev("trade", "BUY 1 ACTUSDT @ $1 (fee $0.001)", "c1"),
    ];
    const { container } = render(<EventsFeed events={events} />);
    expect(container.querySelectorAll(".cycle")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /solo operazioni/i }));
    expect(container.querySelectorAll(".cycle")).toHaveLength(1);
    expect(screen.queryByText("hold")).not.toBeInTheDocument();
  });

  it("badges out-of-schedule wakes", () => {
    render(<EventsFeed events={[
      ev("decision", "ciclo decisione fuori ciclo (LLM): vendo tutto — 1 operazioni, 0 saltate, 0 errori", "c1"),
    ]} />);
    expect(screen.getByText("risveglio")).toBeInTheDocument();
    expect(screen.getByText("vendo tutto")).toBeInTheDocument();
  });

  it("renders a failed cycle as an error", () => {
    render(<EventsFeed events={[ev("decision", "ciclo decisione (LLM): errore — timeout LLM", "c1")]} />);
    expect(screen.getByText("errore")).toBeInTheDocument();
    expect(screen.getByText(/timeout LLM/)).toBeInTheDocument();
  });

  it("surfaces skipped and failed actions as chips only when > 0", () => {
    render(<EventsFeed events={[
      ev("decision", "ciclo decisione (LLM): provo tre cose — 1 operazioni, 2 saltate, 1 errori", "c1"),
      ev("decision", "ciclo decisione (LLM): hold — 0 operazioni, 0 saltate, 0 errori", "c0"),
    ]} />);
    expect(screen.getByText("2 azioni saltate")).toBeInTheDocument();
    expect(screen.getByText("1 errore di esecuzione")).toBeInTheDocument();
    expect(screen.queryByText(/0 azioni saltate/)).not.toBeInTheDocument();
  });

  it("shows a quiet italic note when the agent left none", () => {
    render(<EventsFeed events={[
      ev("decision", "ciclo decisione (LLM): (no note) — 0 operazioni, 0 saltate, 0 errori", "c1"),
    ]} />);
    expect(screen.getByText(/nessuna nota/)).toBeInTheDocument();
  });

  it("renders a null-cycle trade (heartbeat guardrail) as its own badged group", () => {
    const { container } = render(
      <EventsFeed events={[ev("trade", "SELL 1 BTCUSDT @ $80 (fee $0.08)", null)]} />,
    );
    expect(screen.getByText("guardrail")).toBeInTheDocument();
    const move = container.querySelector(".move")! as HTMLElement;
    expect(within(move).getByText("SELL")).toBeInTheDocument();
    expect(move.textContent).toContain("BTC");
  });

  it("groups cycles under day separators", () => {
    const events = [
      ev("decision", "ciclo decisione (LLM): hold — 0 operazioni, 0 saltate, 0 errori", "c2", "2026-06-30T10:00:00Z"),
      ev("decision", "ciclo decisione (LLM): hold ancora — 0 operazioni, 0 saltate, 0 errori", "c1", "2026-06-29T10:00:00Z"),
    ];
    const { container } = render(<EventsFeed events={events} />);
    const labels = [...container.querySelectorAll(".day-label")].map((e) => e.textContent);
    expect(labels).toHaveLength(2);
    expect(labels[0]).toMatch(/30 giugno/);
    expect(labels[1]).toMatch(/29 giugno/);
  });

  it("shows an empty hint with no events", () => {
    render(<EventsFeed events={[]} />);
    expect(screen.getByText(/nessuna attività/i)).toBeInTheDocument();
  });
});
