import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MetricsPanel } from "../components/MetricsPanel";

describe("MetricsPanel", () => {
  it("shows return, drawdown and hit-rate", () => {
    render(
      <MetricsPanel
        metrics={{
          return_pct: "-10", max_drawdown_pct: "25", sharpe: "0.4",
          hit_rate_24h: "75", hit_rate_7d: null,
          benchmarks: { hodl_btc: { return_pct: "10", max_drawdown_pct: "5", sharpe: "0.9" } },
        }}
      />,
    );
    expect(screen.getByTestId("metrics-panel")).toBeInTheDocument();
    expect(screen.getByText(/Max drawdown/i)).toBeInTheDocument();
    expect(screen.getByText(/75%/)).toBeInTheDocument();
  });

  it("renders an empty state when metrics are null", () => {
    render(<MetricsPanel metrics={null} />);
    expect(screen.getByTestId("metrics-panel")).toBeInTheDocument();
  });
});
