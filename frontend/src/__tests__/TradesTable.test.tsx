import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { TradesTable } from "../components/TradesTable";
import type { Trade } from "../api";

const trade = (over: Partial<Trade> = {}): Trade => ({
  id: 1, symbol: "BTCUSDT", side: "BUY", quantity: "0.5", price: "100",
  fee: "0.05", timestamp: "2026-07-01T09:40:00Z", ...over,
});

describe("TradesTable", () => {
  it("renders one row per trade with side tag, coin, and notional value", () => {
    render(
      <TradesTable
        trades={[
          trade({ id: 2, side: "SELL", symbol: "ETHUSDT", quantity: "2", price: "50" }),
          trade({ id: 1 }),
        ]}
      />,
    );
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("ETH")).toBeInTheDocument();   // USDT suffix stripped
    expect(screen.getByText("BTC")).toBeInTheDocument();
    // notional (usd, sempre 2 decimali) distinto dal prezzo (price, decimali variabili)
    expect(screen.getByText("$100.00")).toBeInTheDocument(); // SELL: 2 × $50
    expect(screen.getByText("$50.00")).toBeInTheDocument();  // BUY: 0.5 × $100
    expect(screen.getByText("$100")).toBeInTheDocument();    // prezzo BUY
    expect(screen.getByText("$50")).toBeInTheDocument();     // prezzo SELL
  });

  it("prefixes the day for trades not from today", () => {
    render(<TradesTable trades={[trade({ timestamp: "2026-01-05T10:00:00Z" })]} />);
    expect(screen.getByText(/5 gen/)).toBeInTheDocument();
  });

  it("omits the day prefix for today's trades", () => {
    const now = new Date().toISOString();
    const { container } = render(<TradesTable trades={[trade({ timestamp: now })]} />);
    const cell = container.querySelector("tbody td")!;
    expect(cell.textContent).toMatch(/^\d{2}:\d{2}$/);
  });

  it("shows an empty hint with no trades", () => {
    render(<TradesTable trades={[]} />);
    expect(screen.getByText(/nessuna operazione/i)).toBeInTheDocument();
  });
});
