import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BenchmarkChart } from "../components/BenchmarkChart";

describe("BenchmarkChart", () => {
  it("renders the overlay container with agent + benchmark data", () => {
    render(
      <BenchmarkChart
        equity={[{ timestamp: "2026-07-01T00:00:00Z", equity_usd: "100" }]}
        benchmarks={[
          { kind: "hodl_btc", timestamp: "2026-07-01T00:00:00Z", equity_usd: "100" },
          { kind: "random_p10", timestamp: "2026-07-01T00:00:00Z", equity_usd: "95" },
          { kind: "random_p90", timestamp: "2026-07-01T00:00:00Z", equity_usd: "105" },
        ]}
      />,
    );
    expect(screen.getByTestId("benchmark-chart")).toBeInTheDocument();
  });
});
