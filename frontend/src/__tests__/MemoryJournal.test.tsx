import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MemoryJournal } from "../components/MemoryJournal";

describe("MemoryJournal", () => {
  it("renders active and superseded entries", () => {
    render(
      <MemoryJournal
        entries={[
          { section: "coin_theses", content: "BTC+ETH: merged", cycle_id: "c2", active: true,
            created_at: "2026-07-02T00:00:00Z" },
          { section: "coin_theses", content: "BTC: bull", cycle_id: "c1", active: false,
            created_at: "2026-07-01T00:00:00Z" },
        ]}
      />,
    );
    expect(screen.getByTestId("memory-journal")).toBeInTheDocument();
    expect(screen.getByText("BTC+ETH: merged")).toBeInTheDocument();
    expect(screen.getByText("BTC: bull")).toBeInTheDocument();
  });

  it("renders an empty state when there are no entries", () => {
    render(<MemoryJournal entries={[]} />);
    expect(screen.getByTestId("memory-journal")).toBeInTheDocument();
    expect(screen.getByText(/giornale vuoto/i)).toBeInTheDocument();
  });
});
