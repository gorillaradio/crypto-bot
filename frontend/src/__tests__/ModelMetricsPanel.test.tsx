import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ModelMetricsPanel } from "../components/ModelMetricsPanel";

describe("ModelMetricsPanel", () => {
  it("renders a row per model with rounded hit-rates", () => {
    render(<ModelMetricsPanel models={[
      { model_name: "deepseek/x", n_scored_actions: 4, hit_rate_24h: "75", hit_rate_7d: null },
    ]} />);
    expect(screen.getByTestId("model-metrics-panel")).toBeInTheDocument();
    expect(screen.getByText("deepseek/x")).toBeInTheDocument();
    expect(screen.getByText(/75\.0%/)).toBeInTheDocument();
  });

  it("renders an empty state when there are no models", () => {
    render(<ModelMetricsPanel models={[]} />);
    expect(screen.getByTestId("model-metrics-panel")).toBeInTheDocument();
  });
});
