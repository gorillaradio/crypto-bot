import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MetricsPanel } from "../components/MetricsPanel";

describe("MetricsPanel", () => {
  it("shows return, drawdown and hit-rates labelled by configured window", () => {
    render(
      <MetricsPanel
        metrics={{
          return_pct: "-10", max_drawdown_pct: "25", sharpe: "0.4",
          hit_rates: [{ window: "12h", hit_rate: "75" }, { window: "3d", hit_rate: null }],
          benchmarks: { hodl_btc: { return_pct: "10", max_drawdown_pct: "5", sharpe: "0.9" } },
        }}
      />,
    );
    expect(screen.getByTestId("metrics-panel")).toBeInTheDocument();
    expect(screen.getByText(/Max drawdown/i)).toBeInTheDocument();
    // le etichette vengono dalla risposta, non sono cablate a 24h/7d
    expect(screen.getByText("Hit-rate 12h")).toBeInTheDocument();
    expect(screen.getByText("Hit-rate 3d")).toBeInTheDocument();
    expect(screen.getByText(/75\.0%/)).toBeInTheDocument();
  });

  it("renders an empty state when metrics are null", () => {
    render(<MetricsPanel metrics={null} />);
    expect(screen.getByTestId("metrics-panel")).toBeInTheDocument();
  });
});
