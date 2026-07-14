import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { Sparkline } from "../components/Sparkline";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(globalThis, "fetch");
});

describe("Sparkline", () => {
  it("renders supplied lifecycle closes without calling a browser market API", () => {
    render(<Sparkline symbol="BTCUSDT" closes={[100, 105, 110]} />);
    expect(screen.getByRole("img", { name: /andamento 24h in rialzo/i })).toBeInTheDocument();
    expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled();
  });

  it("renders an upward trend in green with a positive signed %", () => {
    const { container } = render(<Sparkline symbol="BTCUSDT" closes={[100, 102, 105, 110]} />);
    expect(container.querySelector(".spark.pos")).not.toBeNull();
    expect(container.querySelector("svg path")).not.toBeNull();
    expect(screen.getByText(/▲ \+10\.0%/)).toBeInTheDocument(); // (110-100)/100
  });

  it("renders a downward trend in red with a negative signed %", () => {
    const { container } = render(<Sparkline symbol="ETHUSDT" closes={[100, 95, 90]} />);
    expect(container.querySelector(".spark.neg")).not.toBeNull();
    expect(screen.getByText(/▼ −10\.0%/)).toBeInTheDocument();
  });

  it("shows the unavailable placeholder for null or insufficient closes", () => {
    const { container, rerender } = render(<Sparkline symbol="FOOUSDT" closes={null} />);
    expect(container.querySelector(".spark-na")).not.toBeNull();
    expect(container.querySelector("svg")).toBeNull();

    rerender(<Sparkline symbol="FOOUSDT" closes={[]} />);
    expect(container.querySelector("svg")).toBeNull();
  });
});
