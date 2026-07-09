import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ClosedPositionsTable } from "../components/ClosedPositionsTable";
import type { ClosedPosition } from "../api";

const row: ClosedPosition = {
  symbol: "SYNUSDT", opened_at: "2026-07-09T10:10:00Z", closed_at: "2026-07-09T10:21:00Z",
  held_minutes: 11, invested_usd: "20", realized_total_usd: "2.80",
  realized_total_pct: "14.1", close_cycle_id: "c1",
};

describe("ClosedPositionsTable", () => {
  it("racconta l'arco: tempi, tenuta, investito, esito colorato", () => {
    render(<ClosedPositionsTable closed={[row]} />);
    expect(screen.getByText("SYN")).toBeInTheDocument();
    expect(screen.getByText(/11 min/)).toBeInTheDocument();
    expect(screen.getByText(/~\$20/)).toBeInTheDocument();
    const esito = screen.getByText(/\+14[.,]1/);
    expect(esito.closest(".pos")).not.toBeNull();
  });

  it("perdita in rosso", () => {
    render(<ClosedPositionsTable closed={[{ ...row, realized_total_usd: "-0.9",
                                            realized_total_pct: "-3.1" }]} />);
    expect(screen.getByText(/−3[.,]1/).closest(".neg")).not.toBeNull();
  });

  it("empty state", () => {
    render(<ClosedPositionsTable closed={[]} />);
    expect(screen.getByText(/nessuna posizione chiusa/i)).toBeInTheDocument();
  });
});
