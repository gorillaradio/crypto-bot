import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "../components/PositionsTable";
import type { Position } from "../api";

const pos = (over: Partial<Position> = {}): Position => ({
  symbol: "BTCUSDT", quantity: "2", avg_price: "100", cost_basis: "200",
  last_price: "150", unrealized_pnl_pct: "50", market_value: "300", ...over,
});

describe("PositionsTable", () => {
  it("shows P&L percent and market value", () => {
    render(<PositionsTable positions={[pos()]} />);
    expect(screen.getByText("+50.00%")).toBeInTheDocument();
    expect(screen.getByText("$300.00")).toBeInTheDocument();
  });

  it("shows a dash when P&L is unavailable", () => {
    render(<PositionsTable positions={[pos({ last_price: null, unrealized_pnl_pct: null, market_value: null })]} />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);   // Valore + P&L
  });
});
