import { render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EventsFeed } from "../components/EventsFeed";
import type { AgentEvent } from "../api";

const ev = (kind: string, message: string, cycle_id: string | null): AgentEvent => ({
  timestamp: "2026-06-29T09:40:39Z", kind, message, cycle_id,
});

describe("EventsFeed", () => {
  it("groups a cycle's events under one CICLO head with the moves nested", () => {
    // API order is desc: reflection, decision, then moves.
    const events = [
      ev("reflection", "memoria aggiornata dopo trade chiuso", "c1"),
      ev("decision", "ciclo decisione (LLM): trim AEVO, add ACT — 2 operazioni, 0 saltate, 0 errori", "c1"),
      ev("reasoning", "ACT momentum continues, adding", "c1"),
      ev("trade", "BUY 378 ACTUSDT @ $0.0132 (fee $0.005)", "c1"),
    ];
    const { container } = render(<EventsFeed events={events} />);

    // exactly one cycle group
    const cycles = container.querySelectorAll(".cycle");
    expect(cycles).toHaveLength(1);

    // CICLO prefix is stripped in the head
    const head = container.querySelector(".cycle-head")!;
    expect(head.textContent).toContain("trim AEVO, add ACT");
    expect(head.textContent).not.toContain("ciclo decisione");

    // trade + reasoning live inside the moves thread; reflection is the footer
    const moves = container.querySelector(".cycle-moves")!;
    expect(within(moves as HTMLElement).getByText(/BUY 378 ACTUSDT/)).toBeInTheDocument();
    expect(within(moves as HTMLElement).getByText(/ACT momentum continues/)).toBeInTheDocument();
    expect(container.querySelector(".cycle-foot")!.textContent).toContain("memoria aggiornata");
  });

  it("renders separate cycles for distinct cycle_ids", () => {
    const events = [
      ev("decision", "ciclo decisione (LLM): hold — 0 operazioni, 0 saltate, 0 errori", "c2"),
      ev("decision", "ciclo decisione (LLM): buy — 1 operazioni, 0 saltate, 0 errori", "c1"),
      ev("trade", "BUY 1 BTCUSDT @ $100 (fee $0.1)", "c1"),
    ];
    const { container } = render(<EventsFeed events={events} />);
    expect(container.querySelectorAll(".cycle")).toHaveLength(2);
  });

  it("renders a null-cycle event (heartbeat sell) as its own bare group", () => {
    const events = [ev("trade", "SELL 1 BTCUSDT @ $80 (fee $0.08)", null)];
    const { container } = render(<EventsFeed events={events} />);
    expect(container.querySelector(".cycle-head")).toBeNull();      // no decision head
    expect(container.querySelector(".cycle-moves.bare")).not.toBeNull();
    expect(screen.getByText(/SELL 1 BTCUSDT/)).toBeInTheDocument();
  });

  it("shows an empty hint with no events", () => {
    render(<EventsFeed events={[]} />);
    expect(screen.getByText(/nessuna attività/i)).toBeInTheDocument();
  });
});
