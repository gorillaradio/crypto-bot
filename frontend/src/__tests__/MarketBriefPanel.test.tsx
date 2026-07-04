import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BriefView } from "../components/MarketBriefPanel";
import type { MarketBrief } from "../api";

const brief: MarketBrief = {
  regime: "risk-off",
  highlights: [{ symbol: "SOLUSDT", snapshot: "s", signal: "bullish", note: "breakout" }],
  key_news: ["ETF delayed"],
  as_of: "2026-07-04T10:00:00Z",
};

describe("BriefView", () => {
  it("renders regime, highlight and key news", () => {
    render(<BriefView brief={brief} />);
    expect(screen.getByText("risk-off")).toBeInTheDocument();
    expect(screen.getByText("SOL")).toBeInTheDocument();
    expect(screen.getByText(/breakout/)).toBeInTheDocument();
    expect(screen.getByText("ETF delayed")).toBeInTheDocument();
  });
});
