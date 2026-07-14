import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PositionsTable } from "../components/PositionsTable";
import type { LifecycleSummary } from "../api";

vi.mock("../components/OpenLifecycleDetail", () => ({
  OpenLifecycleDetail: ({ lifecycleId, onClose }: { lifecycleId: string; onClose: () => void }) => (
    <div>
      <span>{`detail:${lifecycleId}`}</span>
      <button type="button" onClick={onClose}>Chiudi dettaglio</button>
    </div>
  ),
}));

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
const detailProps = { agentId: 1, onAuthLost: vi.fn() };

describe("PositionsTable", () => {
  it.each(["open", "closed", "all"] as const)("renders the API sparkline in %s", (state) => {
    render(<PositionsTable {...detailProps} state={state} market={staleMarket} items={[lifecycle({ market_series_24h: ["100", "110"] })]} />);

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
    render(<PositionsTable {...detailProps} state="open" market={unavailableMarket} items={[lifecycle({ market_series_24h: null })]} />);

    expect(screen.getByText(/dati di mercato non disponibili/i)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /andamento 24h/i })).not.toBeInTheDocument();
  });

  it("mostra le colonne comparative delle aperte senza dettaglio o ordinamento manuale", () => {
    render(<PositionsTable {...detailProps} items={[lifecycle()]} market={freshMarket} state="open" />);

    for (const heading of ["Coin", "Età", "Esposizione", "Peso", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(/dati di mercato aggiornati/i)).toBeInTheDocument();
    expect(screen.getByText(/\+\$99\.00 · \+49\.50%/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ordina/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toBeInTheDocument();
  });

  it("mostra le colonne comparative delle chiuse", () => {
    render(<PositionsTable {...detailProps} items={[lifecycle({
      status: "closed", closed_at: "2026-07-10T11:10:00Z", held_minutes: 1500,
      quantity: null, exposure_usd: null, portfolio_weight_pct: null,
    })]} market={freshMarket} state="closed" />);

    for (const heading of ["Coin", "Chiusa", "Durata", "Investito", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Esposizione" })).not.toBeInTheDocument();
  });

  it("mostra uno schema comune nella vista tutte", () => {
    render(<PositionsTable {...detailProps} items={[lifecycle()]} market={freshMarket} state="all" />);

    for (const heading of ["Coin", "Stato", "Ultima attività", "Capitale", "Risultato netto"])
      expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
  });

  it.each([
    ["open", "Nessuna posizione aperta — tutto il capitale è in cash."],
    ["closed", "Nessuna posizione chiusa nel periodo selezionato. Amplia il periodo o scegli tutto lo storico."],
    ["all", "Non esiste ancora alcun lifecycle. Comparirà qui dopo la prima apertura dell’agente."],
  ] as const)("usa l'empty state specifico per %s", (state, copy) => {
    render(<PositionsTable {...detailProps} items={[]} market={freshMarket} state={state} />);
    expect(screen.getByText(copy)).toBeInTheDocument();
  });

  it("selects an open row and replaces only the right comparison columns", () => {
    const items = [lifecycle(), lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT" })];
    const view = render(
      <PositionsTable {...detailProps} state="open" market={freshMarket} items={items} />,
    );
    const before = screen.getAllByRole("row").slice(1).map(row => row.textContent);
    const columnsBefore = [...view.container.querySelectorAll("col")].map(column => column.className);

    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));

    expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Selezionata")).toBeInTheDocument();
    expect(screen.getByText("detail:life-1")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Coin" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "24h" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Età" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Dettaglio" })).toHaveAttribute("colspan", "3");
    for (const heading of ["Esposizione", "Peso", "Risultato netto"])
      expect(screen.queryByRole("columnheader", { name: heading })).not.toBeInTheDocument();
    expect(before.map(text => text?.match(/BTC|ETH/)?.[0])).toEqual(["BTC", "ETH"]);

    const columnsAfter = [...view.container.querySelectorAll("col")].map(column => column.className);
    expect(columnsAfter).toEqual(columnsBefore);
    expect(columnsAfter.slice(0, 3)).toEqual(expect.arrayContaining(["w-[8rem]", "w-[7rem]", "w-[5rem]"]));

    const detailCell = screen.getByText("detail:life-1").closest("td");
    expect(detailCell).toHaveAttribute("rowspan", String(items.length));
    expect(detailCell).toHaveAttribute("colspan", "3");
    expect(detailCell).toHaveClass("align-top", "whitespace-normal");
  });

  it("changes selection directly and permits only open rows", () => {
    render(
      <PositionsTable
        {...detailProps}
        state="all"
        market={freshMarket}
        items={[
          lifecycle(),
          lifecycle({ lifecycle_id: "life-2", symbol: "SOLUSDT" }),
          lifecycle({ lifecycle_id: "life-closed", symbol: "ETHUSDT", status: "closed" }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
    expect(screen.getByText("detail:life-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli SOL" }));
    expect(screen.getByText("detail:life-2")).toBeInTheDocument();
    expect(screen.queryByText("detail:life-1")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apri dettagli ETH" })).not.toBeInTheDocument();
    expect(screen.getByText("ETH")).toBeInTheDocument();
  });

  it("freezes visible identity/order during polls, updates values, then restores collection order", async () => {
    const first = lifecycle({ lifecycle_id: "life-1", symbol: "BTCUSDT", exposure_usd: "100" });
    const second = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "50" });
    const liveOpenedAt = new Date(Date.now() - 20.5 * 60_000).toISOString();
    const view = render(
      <PositionsTable {...detailProps} state="open" market={freshMarket} items={[first, second]} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
    view.rerender(
      <PositionsTable
        {...detailProps}
        state="open"
        market={freshMarket}
        items={[{ ...second, exposure_usd: "200" }, { ...first, opened_at: liveOpenedAt, exposure_usd: "110" }]}
      />,
    );

    expect(screen.getAllByRole("button", { name: /Apri dettagli/ }).map(button => button.textContent)).toEqual(["BTC", "ETH"]);
    expect(screen.getByText("20m")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chiudi dettaglio" }));
    expect(screen.getAllByRole("button", { name: /Apri dettagli/ }).map(button => button.textContent)).toEqual(["ETH", "BTC"]);
    expect(screen.getByText("$200.00")).toBeInTheDocument();
    expect(screen.getByText("$110.00")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toHaveFocus());
  });

  it("keeps a missing frozen lifecycle snapshot visible until detail closes", () => {
    const snapshotOpenedAt = new Date(Date.now() - 10.5 * 60_000).toISOString();
    const first = lifecycle({ lifecycle_id: "life-1", symbol: "BTCUSDT", opened_at: snapshotOpenedAt, exposure_usd: "100" });
    const second = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "50" });
    const view = render(
      <PositionsTable {...detailProps} state="open" market={freshMarket} items={[first, second]} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
    view.rerender(
      <PositionsTable {...detailProps} state="open" market={freshMarket} items={[{ ...second, exposure_usd: "200" }]} />,
    );

    expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Apri dettagli/ }).map(button => button.textContent)).toEqual(["BTC", "ETH"]);
    expect(screen.getByText("10m")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chiudi dettaglio" }));
    expect(screen.queryByRole("button", { name: "Apri dettagli BTC" })).not.toBeInTheDocument();
    expect(screen.getByText("$200.00")).toBeInTheDocument();
  });

  it("does not animate or transform lifecycle body rows", () => {
    const view = render(
      <PositionsTable
        {...detailProps}
        state="open"
        market={freshMarket}
        items={[lifecycle(), lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT" })]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));

    for (const row of view.container.querySelectorAll("tbody tr")) {
      expect(row.className).not.toMatch(/(?:^|\s)animate-/);
      expect(row.className).not.toMatch(/(?:^|\s)transition-(?:all|colors|transform)(?:\s|$)/);
      expect(row).not.toHaveStyle({ transform: expect.any(String) });
    }
  });
});
