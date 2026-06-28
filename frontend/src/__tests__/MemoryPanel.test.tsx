import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryPanel } from "../components/MemoryPanel";

describe("MemoryPanel", () => {
  it("renders non-empty sections as list items", () => {
    render(<MemoryPanel memory={{ coin_theses: "BTC: bull\nETH: flat", trade_lessons: "", strategy_notes: "patient" }} />);
    expect(screen.getByText("BTC: bull")).toBeInTheDocument();
    expect(screen.getByText("ETH: flat")).toBeInTheDocument();
    expect(screen.getByText("patient")).toBeInTheDocument();
  });

  it("shows an empty hint when all sections are blank", () => {
    render(<MemoryPanel memory={{ coin_theses: "", trade_lessons: "", strategy_notes: "" }} />);
    expect(screen.getByText(/nessuna memoria/i)).toBeInTheDocument();
  });
});
