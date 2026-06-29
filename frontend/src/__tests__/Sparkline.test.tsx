import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../api", () => ({ getKlines: vi.fn() }));
import { getKlines } from "../api";
import { Sparkline } from "../components/Sparkline";

beforeEach(() => vi.mocked(getKlines).mockReset());

describe("Sparkline", () => {
  it("renders an upward trend in green with a positive signed %", async () => {
    vi.mocked(getKlines).mockResolvedValue([100, 102, 105, 110]);
    const { container } = render(<Sparkline symbol="BTCUSDT" />);
    await waitFor(() => expect(container.querySelector(".spark.pos")).not.toBeNull());
    expect(container.querySelector("svg path")).not.toBeNull();
    expect(screen.getByText(/▲ \+10\.0%/)).toBeInTheDocument(); // (110-100)/100
  });

  it("renders a downward trend in red with a negative signed %", async () => {
    vi.mocked(getKlines).mockResolvedValue([100, 95, 90]);
    const { container } = render(<Sparkline symbol="ETHUSDT" />);
    await waitFor(() => expect(container.querySelector(".spark.neg")).not.toBeNull());
    expect(screen.getByText(/▼ −10\.0%/)).toBeInTheDocument();
  });

  it("shows a placeholder when there isn't enough data", async () => {
    vi.mocked(getKlines).mockResolvedValue([]);
    const { container } = render(<Sparkline symbol="FOOUSDT" />);
    await waitFor(() => expect(container.querySelector(".spark-na")).not.toBeNull());
    expect(container.querySelector("svg")).toBeNull();
  });
});
