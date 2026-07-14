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

const freshMarket = { status: "fresh", as_of: "2026-07-09T10:20:00Z" } as const;
const staleMarket = { status: "stale", as_of: "2026-07-09T10:20:00Z" } as const;
const unavailableMarket = { status: "unavailable", as_of: null } as const;

describe("PositionsTable", () => {
  it.each(["open", "closed", "all"] as const)("renders the API sparkline in %s", (state) => {
    render(<PositionsTable state={state} market={staleMarket} items={[lifecycle({ market_series_24h: ["100", "110"] })]} />);

    expect(screen.getByRole("columnheader", { name: "24h" })).toBeInTheDocument();
    const [coinHeading, chartHeading] = screen.getAllByRole("columnheader");
    expect([coinHeading, chartHeading].map((heading) => heading.textContent)).toEqual(["Coin", "24h"]);
    expect(chartHeading).toHaveClass("text-left");
    expect(chartHeading).not.toHaveClass("text-right");
    const chartCell = screen.getAllByRole("cell")[1];
    expect(chartCell).toHaveClass("text-left");
    expect(chartCell).not.toHaveClass("text-right");
    expect(screen.getByRole("img", { name: /andamento 24h/i })).toBeInTheDocument();
    expect(screen.getByText(/dato di mercato non aggiornato/i)).toHaveTextContent("2026-07-09T10:20:00Z");
  });

  it("declares unavailable market data without a fabricated chart", () => {
    render(<PositionsTable state="open" market={unavailableMarket} items={[lifecycle({ market_series_24h: null })]} />);

    expect(screen.getByText(/dati di mercato non disponibili/i)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /andamento 24h/i })).not.toBeInTheDocument();
  });

  it("mostra le colonne comparative delle aperte senza dettaglio o ordinamento manuale", () => {
    render(<PositionsTable items={[lifecycle()]} market={freshMarket} state="open" />);

    for (const heading of ["Coin", "Età", "Esposizione", "Peso", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(/dati di mercato aggiornati/i)).toBeInTheDocument();
    expect(screen.getByText(/\+\$99\.00 · \+49\.50%/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ordina/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dettagli/i })).not.toBeInTheDocument();
  });

  it("mostra le colonne comparative delle chiuse", () => {
    render(<PositionsTable items={[lifecycle({
      status: "closed", closed_at: "2026-07-10T11:10:00Z", held_minutes: 1500,
      quantity: null, exposure_usd: null, portfolio_weight_pct: null,
    })]} market={freshMarket} state="closed" />);

    for (const heading of ["Coin", "Chiusa", "Durata", "Investito", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Esposizione" })).not.toBeInTheDocument();
  });

  it("mostra uno schema comune nella vista tutte", () => {
    render(<PositionsTable items={[lifecycle()]} market={freshMarket} state="all" />);

    for (const heading of ["Coin", "Stato", "Ultima attività", "Capitale", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
  });

  it.each([
    ["open", "Nessuna posizione aperta — tutto il capitale è in cash."],
    ["closed", "Nessuna posizione chiusa nel periodo selezionato. Amplia il periodo o scegli tutto lo storico."],
    ["all", "Non esiste ancora alcun lifecycle. Comparirà qui dopo la prima apertura dell’agente."],
  ] as const)("usa l'empty state specifico per %s", (state, copy) => {
    render(<PositionsTable items={[]} market={freshMarket} state={state} />);
    expect(screen.getByText(copy)).toBeInTheDocument();
  });
});
