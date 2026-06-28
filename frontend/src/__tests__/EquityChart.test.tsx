import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EquityChart } from "../components/EquityChart";

describe("EquityChart", () => {
  it("renders the chart container with data", () => {
    render(<EquityChart data={[{ timestamp: "2026-06-28T00:00:00Z", equity_usd: "100" }]} />);
    expect(screen.getByTestId("equity-chart")).toBeInTheDocument();
  });
});
