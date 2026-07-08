import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ModelMetricsPanel } from "../components/ModelMetricsPanel";

describe("ModelMetricsPanel", () => {
  it("renders a row per model with columns from the configured windows", () => {
    render(<ModelMetricsPanel models={[
      { model_name: "deepseek/x", n_scored_actions: 4,
        hit_rates: [{ window: "12h", hit_rate: "75" }, { window: "3d", hit_rate: null }] },
    ]} />);
    expect(screen.getByTestId("model-metrics-panel")).toBeInTheDocument();
    expect(screen.getByText("deepseek/x")).toBeInTheDocument();
    expect(screen.getByText("Hit-rate 12h")).toBeInTheDocument();  // intestazioni dinamiche
    expect(screen.getByText("Hit-rate 3d")).toBeInTheDocument();
    expect(screen.getByText(/75\.0%/)).toBeInTheDocument();
  });

  it("renders an empty state when there are no models", () => {
    render(<ModelMetricsPanel models={[]} />);
    expect(screen.getByTestId("model-metrics-panel")).toBeInTheDocument();
  });
});
