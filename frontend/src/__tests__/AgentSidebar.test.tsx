import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AgentSidebar } from "../components/AgentSidebar";
import type { Agent } from "../api";

const agent = (over: Partial<Agent>): Agent => ({
  id: 1, name: "A", status: "running", instructions: "",
  cash_usd: "0", equity: "100", return_pct: "0",
  duration_start: "2026-06-29T00:00:00Z", duration_end: "", ...over,
});

const base = [
  agent({ id: 1, name: "Basso", equity: "90", return_pct: "-10" }),
  agent({ id: 2, name: "Alto", equity: "130", return_pct: "30" }),
  agent({ id: 3, name: "Medio", equity: "110", return_pct: "10" }),
];

describe("AgentSidebar", () => {
  it("ranks agents by equity descending (leaderboard)", () => {
    render(<AgentSidebar agents={base} selId={2} onSelect={() => {}} onCreate={() => {}} />);
    const names = [...document.querySelectorAll(".rail-name")].map((n) => n.textContent);
    expect(names).toEqual(["Alto", "Medio", "Basso"]);
  });

  it("marks the selected agent with aria-current", () => {
    render(<AgentSidebar agents={base} selId={3} onSelect={() => {}} onCreate={() => {}} />);
    const current = document.querySelector('[aria-current="true"]');
    expect(current?.textContent).toContain("Medio");
  });

  it("calls onSelect with the clicked agent id", () => {
    const onSelect = vi.fn();
    render(<AgentSidebar agents={base} selId={2} onSelect={onSelect} onCreate={() => {}} />);
    fireEvent.click(screen.getByText("Basso"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("calls onCreate from the add button", () => {
    const onCreate = vi.fn();
    render(<AgentSidebar agents={base} selId={2} onSelect={() => {}} onCreate={onCreate} />);
    fireEvent.click(screen.getByText(/nuovo agente/i));
    expect(onCreate).toHaveBeenCalledOnce();
  });
});
