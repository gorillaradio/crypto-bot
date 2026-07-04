import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DecisionsPanel } from "../components/DecisionsPanel";
import type { Decision } from "../api";

const dec = (over: Partial<Decision> = {}): Decision => ({
  id: 1, cycle_id: "c1", kind: "decision", trigger: "schedule",
  parsed_output: '{"actions":[{"type":"BUY","symbol":"SOLUSDT"},{"type":"HOLD"}],"note":""}',
  parse_status: "ok", model_name: "deepseek/x", latency_ms: 1200,
  created_at: "2026-07-04T10:00:00Z", ...over,
});

describe("DecisionsPanel", () => {
  it("summarizes decision actions compactly", () => {
    render(<DecisionsPanel decisions={[dec()]} />);
    expect(screen.getByText("BUY SOL, HOLD")).toBeInTheDocument();
    expect(screen.getByText("schedule")).toBeInTheDocument();
  });

  it("shows a dash for non-decision kinds", () => {
    render(<DecisionsPanel decisions={[dec({ kind: "reflection", parsed_output: null })]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows an empty hint with no decisions", () => {
    render(<DecisionsPanel decisions={[]} />);
    expect(screen.getByText(/nessuna decisione/i)).toBeInTheDocument();
  });
});
