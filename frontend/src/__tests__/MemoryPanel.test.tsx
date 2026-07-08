import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryPanel } from "../components/MemoryPanel";
import type { AgentMemory, MemoryEntry } from "../api";

const memory = (over: Partial<AgentMemory> = {}): AgentMemory => ({
  coin_theses: "", trade_lessons: "", strategy_notes: "",
  self_policy: [], caps: { coin_theses: 8, trade_lessons: 10, strategy_notes: 5, self_policy: 8 },
  ...over,
});

const entry = (over: Partial<MemoryEntry> = {}): MemoryEntry => ({
  section: "coin_theses", content: "BTC: bull", cycle_id: "c1", active: true,
  created_at: "2026-07-01T10:00:00Z", ...over,
});

describe("MemoryPanel · adesso", () => {
  it("groups active entries by section with fill count and description", () => {
    render(
      <MemoryPanel
        memory={memory({ coin_theses: "BTC: bull\nETH: flat", strategy_notes: "patient" })}
        entries={[]}
      />,
    );
    expect(screen.getByText("BTC: bull")).toBeInTheDocument();
    expect(screen.getByText("ETH: flat")).toBeInTheDocument();
    expect(screen.getByText("patient")).toBeInTheDocument();
    expect(screen.getByText("2/8")).toBeInTheDocument();       // tesi per coin: 2 su 8
    expect(screen.getByText("1/5")).toBeInTheDocument();       // note di strategia: 1 su 5
    expect(screen.getByText(/cosa pensa delle singole coin/)).toBeInTheDocument();
    // sezione vuota: presente con placeholder, non nascosta
    expect(screen.getByText("Lezioni dai trade")).toBeInTheDocument();
    expect(screen.getAllByText(/ancora niente qui/).length).toBeGreaterThan(0);
  });

  it("shows self-imposed rules with their ref", () => {
    render(
      <MemoryPanel
        memory={memory({ self_policy: [{ ref: "P3", content: "mai più del 30% su una coin" }] })}
        entries={[]}
      />,
    );
    expect(screen.getByText("P3")).toBeInTheDocument();
    expect(screen.getByText(/mai più del 30%/)).toBeInTheDocument();
  });

  it("explains how memory forms when everything is empty", () => {
    render(<MemoryPanel memory={memory()} entries={[]} />);
    expect(screen.getByText(/si riempie al primo trade chiuso/i)).toBeInTheDocument();
  });
});

describe("MemoryPanel · cronologia", () => {
  it("switches to the day-grouped journal with retired entries marked", () => {
    render(
      <MemoryPanel
        memory={memory()}
        entries={[
          entry({ content: "BTC+ETH: merged", created_at: "2026-07-02T09:00:00Z" }),
          entry({ content: "BTC: bull", active: false, created_at: "2026-07-01T08:00:00Z" }),
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /cronologia/i }));

    expect(screen.getByText("BTC+ETH: merged")).toBeInTheDocument();
    expect(screen.getByText("BTC: bull")).toBeInTheDocument();
    expect(screen.getByText("ritirata")).toBeInTheDocument();       // la voce inattiva è marcata
    expect(screen.getByText(/2 voci · 1 attive/)).toBeInTheDocument();
    // due giorni distinti → due separatori
    expect(screen.getByText(/2 luglio/)).toBeInTheDocument();
    expect(screen.getByText(/1 luglio/)).toBeInTheDocument();
  });

  it("labels self_policy entries with the regola badge", () => {
    render(
      <MemoryPanel memory={memory()} entries={[entry({ section: "self_policy", content: "stop a -8%" })]} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /cronologia/i }));
    expect(screen.getByText("regola")).toBeInTheDocument();
    expect(screen.getByText("stop a -8%")).toBeInTheDocument();
  });

  it("shows an empty hint when the journal has no entries", () => {
    render(<MemoryPanel memory={memory()} entries={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /cronologia/i }));
    expect(screen.getByText(/cronologia vuota/i)).toBeInTheDocument();
  });
});
