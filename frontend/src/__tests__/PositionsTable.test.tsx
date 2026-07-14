import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "../components/PositionsTable";
import type { LifecycleSummary } from "../api";

const lifecycle = (over: Partial<LifecycleSummary> = {}): LifecycleSummary => ({
  lifecycle_id: "life-1",
  symbol: "BTCUSDT",
  status: "open",
  opened_at: "2026-07-09T10:10:00Z",
  closed_at: null,
  last_changed_at: "2026-07-09T10:20:00Z",
  quantity: "2",
  exposure_usd: "300",
  portfolio_weight_pct: "25",
  held_minutes: null,
  invested_usd: "200",
  fees_usd: "1",
  net_result_usd: "99",
  net_result_pct: "49.5",
  market_series_24h: null,
  ...over,
});

describe("PositionsTable", () => {
  it("mostra le colonne comparative delle aperte senza dettaglio o ordinamento manuale", () => {
    render(<PositionsTable items={[lifecycle()]} state="open" />);

    for (const heading of ["Coin", "Età", "Esposizione", "Peso", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(/\+\$99\.00 · \+49\.50%/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ordina/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dettagli/i })).not.toBeInTheDocument();
  });

  it("mostra le colonne comparative delle chiuse", () => {
    render(<PositionsTable items={[lifecycle({
      status: "closed", closed_at: "2026-07-10T11:10:00Z", held_minutes: 1500,
      quantity: null, exposure_usd: null, portfolio_weight_pct: null,
    })]} state="closed" />);

    for (const heading of ["Coin", "Chiusa", "Durata", "Investito", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Esposizione" })).not.toBeInTheDocument();
  });

  it("mostra uno schema comune nella vista tutte", () => {
    render(<PositionsTable items={[lifecycle()]} state="all" />);

    for (const heading of ["Coin", "Stato", "Ultima attività", "Capitale", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
  });

  it.each([
    ["open", "Nessuna posizione aperta — tutto il capitale è in cash."],
    ["closed", "Nessuna posizione chiusa nel periodo selezionato. Amplia il periodo o scegli tutto lo storico."],
    ["all", "Non esiste ancora alcun lifecycle. Comparirà qui dopo la prima apertura dell’agente."],
  ] as const)("usa l'empty state specifico per %s", (state, copy) => {
    render(<PositionsTable items={[]} state={state} />);
    expect(screen.getByText(copy)).toBeInTheDocument();
  });
});
