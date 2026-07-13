import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "../components/PositionsTable";
import type { OpenLifecycle, AgentEvent } from "../api";

const pos = (over: Partial<OpenLifecycle> = {}): OpenLifecycle => ({
  lifecycle_id: "life-1", cycle_id: "c1", status: "open",
  symbol: "BTCUSDT", quantity: "2", avg_price: "100", cost_basis: "200",
  last_price: "150", exposure_usd: "300", fees_usd: "1",
  unrealized_usd: "100", net_result_usd: "99", net_result_pct: "49.5",
  opened_at: "2026-07-09T10:10:00Z", last_changed_at: "2026-07-09T10:20:00Z",
  realized_usd: "0", evaluation: null, ...over,
});

describe("PositionsTable", () => {
  it("shows P&L percent and market value", () => {
    render(<PositionsTable positions={[pos()]} events={[]} />);
    expect(screen.getByText("+49.50%")).toBeInTheDocument();
    expect(screen.getByText("$300.00")).toBeInTheDocument();
  });

  it("shows a dash when P&L is unavailable", () => {
    render(<PositionsTable positions={[pos({ last_price: null, exposure_usd: null, unrealized_usd: null, net_result_usd: null, net_result_pct: null })]} events={[]} />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);   // Valore + P&L
  });

  it("mostra storia e già incassato, e retrocede i numeri contabili nel dettaglio", () => {
    const positions = [{
      ...pos(), lifecycle_id: "spell-life", symbol: "SPELLUSDT", quantity: "290419", avg_price: "0.000103",
      cost_basis: "30", last_price: "0.000104", net_result_pct: "1.4",
      exposure_usd: "30.10", opened_at: "2026-07-09T10:10:00Z", realized_usd: "2.20",
    }];
    const events = [{
      timestamp: "2026-07-09T10:21:00Z", kind: "trade", message: "", cycle_id: "c1",
      payload: { side: "SELL", symbol: "SPELLUSDT", qty: "1", price: "0.00012",
                 fee: "0", fraction: "0.5", avg_cost: "0.000103",
                 realized_pnl_pct: "15", realized_pnl_usd: "2.20" },
    }, {
      timestamp: "2026-07-09T10:26:00Z", kind: "trade", message: "", cycle_id: "c2",
      payload: { side: "BUY", symbol: "SPELLUSDT", qty: "1", price: "0.0001",
                 fee: "0", usd_value: "15", position: "increase" },
    }] as AgentEvent[];
    render(<PositionsTable positions={positions as OpenLifecycle[]} events={events} />);
    expect(screen.getByText(/\$2\.20/)).toBeInTheDocument();
    expect(screen.queryByText("Quantità")).not.toBeInTheDocument();   // colonna retrocessa
    // La storia non sta più in riga: compare solo nel dettaglio espanso.
    expect(screen.queryByText(/−50% alle/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /dettagli/i }));
    expect(screen.getByText(/−50% alle/)).toBeInTheDocument();
    expect(screen.getByText(/aumentata alle/)).toBeInTheDocument();
    expect(screen.getByText(/costo medio/i)).toBeInTheDocument();
  });

  it("apre il dettaglio cliccando la riga", () => {
    render(<PositionsTable positions={[pos()]} events={[]} />);
    expect(screen.queryByText(/costo medio/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("BTC"));
    expect(screen.getByText(/costo medio/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText("BTC"));
    expect(screen.queryByText(/costo medio/i)).not.toBeInTheDocument();
  });

  it("usa il lifecycle come identità per due vite dello stesso simbolo", () => {
    render(<PositionsTable positions={[
      pos({ lifecycle_id: "life-a" }),
      pos({ lifecycle_id: "life-b", cycle_id: "c2" }),
    ]} events={[]} />);
    const buttons = screen.getAllByRole("button", { name: /dettagli/i });
    fireEvent.click(buttons[0]);
    expect(screen.getAllByText(/costo medio/i)).toHaveLength(1);
    fireEvent.click(buttons[1]);
    expect(screen.getAllByText(/costo medio/i)).toHaveLength(2);
  });
});
