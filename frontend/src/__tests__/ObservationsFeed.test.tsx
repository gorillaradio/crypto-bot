import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ObservationsFeed } from "../components/ObservationsFeed";
import type { Observation } from "../api";

const obs = (over: Partial<Observation> = {}): Observation => ({
  source: "CoinDesk", title: "BTC rallies", url: "http://x",
  published_at: "2026-07-04T09:00:00Z", symbols: ["BTC"], ...over,
});

describe("ObservationsFeed", () => {
  it("renders a headline as a link with its source and symbols", () => {
    render(<ObservationsFeed observations={[obs()]} />);
    const link = screen.getByText("BTC rallies");
    expect(link).toHaveAttribute("href", "http://x");
    expect(screen.getByText("CoinDesk")).toBeInTheDocument();
    expect(screen.getByText("BTC")).toBeInTheDocument();
  });

  it("renders a headline without url as plain text", () => {
    render(<ObservationsFeed observations={[obs({ url: null })]} />);
    expect(screen.getByText("BTC rallies").tagName).toBe("SPAN");
  });

  it("shows an empty hint", () => {
    render(<ObservationsFeed observations={[]} />);
    expect(screen.getByText(/nessuna osservazione/i)).toBeInTheDocument();
  });
});
