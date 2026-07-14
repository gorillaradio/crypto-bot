import { act, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "../App";

vi.mock("../api", () => ({
  AuthError: class AuthError extends Error {},
  getMe: vi.fn(),
  getAgents: vi.fn(),
  getEquity: vi.fn(() => Promise.resolve([])),
  getBenchmarks: vi.fn(() => Promise.resolve([])),
  getAgentMetrics: vi.fn(() => Promise.resolve(null)),
  getModelMetrics: vi.fn(() => Promise.resolve([])),
  getEvents: vi.fn(() => Promise.resolve([])),
  getTrades: vi.fn(() => Promise.resolve([])),
  getLifecycles: vi.fn(() => Promise.resolve({ items: [], next_cursor: null })),
  getLifecycleDetail: vi.fn(),
  getClosedPositions: vi.fn(() => Promise.resolve([])),
  getDecisions: vi.fn(() => Promise.resolve([])),
  getObservations: vi.fn(() => Promise.resolve([])),
  getMemory: vi.fn(() => Promise.resolve(null)),
  getMemoryJournal: vi.fn(() => Promise.resolve([])),
  getPrompt: vi.fn(() => Promise.resolve(null)),
  getBrief: vi.fn(() => Promise.resolve(null)),
  logout: vi.fn(() => Promise.resolve()),
  exchangeViewerToken: vi.fn(),
}));
import { AuthError, getMe, getAgents, getLifecycles, getLifecycleDetail, exchangeViewerToken } from "../api";

const freshMarket = { status: "fresh", as_of: "2026-07-09T10:20:00Z" };
const lifecyclePage = (items: unknown[], next_cursor: string | null, market = freshMarket) => ({ items, next_cursor, market });
const lifecycle = (over: Record<string, unknown> = {}) => ({
  lifecycle_id: "life-1", symbol: "BTCUSDT", status: "open",
  opened_at: "2026-07-14T09:00:00Z", closed_at: null,
  last_changed_at: "2026-07-14T10:00:00Z", quantity: "1",
  exposure_usd: "100", portfolio_weight_pct: "50", held_minutes: null,
  invested_usd: "100", fees_usd: "0.1", net_result_usd: "5",
  net_result_pct: "5", market_series_24h: ["100", "101"],
  ...over,
});
const btc = lifecycle();
const eth = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "50" });
const btcUpdated = lifecycle({ exposure_usd: "110" });
const ethUpdated = lifecycle({ lifecycle_id: "life-2", symbol: "ETHUSDT", exposure_usd: "200" });
const detailBody = {
  lifecycle_id: "life-1", cycle_id: "hold", symbol: "BTCUSDT", status: "open",
  opened_at: "2026-07-14T09:00:00Z", last_changed_at: "2026-07-14T10:00:00Z",
  evaluation: null,
  economy: {
    quantity: "1", avg_price: "100", last_price: "110", exposure_usd: "110",
    invested_usd: "100", realized_usd: "0", unrealized_usd: "10",
    fees_usd: "0.1", net_result_usd: "9.9", net_result_pct: "9.9",
  },
  market: freshMarket,
  trades: [{
    id: 1, cycle_id: "open", side: "BUY", quantity: "1", price: "100",
    fee: "0.1", timestamp: "2026-07-14T09:00:00Z",
  }],
};

beforeEach(() => {
  vi.mocked(getAgents).mockResolvedValue([] as never);
  vi.mocked(getMe).mockReset();
  vi.mocked(exchangeViewerToken).mockReset();
  window.location.hash = "";
  vi.mocked(getLifecycles).mockReset();
  vi.mocked(getLifecycles).mockResolvedValue(lifecyclePage([], null) as never);
  vi.mocked(getLifecycleDetail).mockReset();
});

const agent = {
  id: 1, name: "Alpha", status: "running", instructions: "",
  cash_usd: "100", equity: "100", return_pct: "0", decision_seconds: 60,
  duration_start: "2026-07-01T00:00:00Z", duration_end: "2026-08-01T00:00:00Z",
};

describe("App auth gate", () => {
  it("shows the login screen when not authenticated", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: null } as never);
    render(<App />);
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
  });

  it("shows the dashboard (with logout) when admin", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "admin" } as never);
    render(<App />);
    // The sidebar renders twice (desktop rail + mobile sheet), so the logout
    // control appears more than once — assert at least one is present.
    await waitFor(() => expect(screen.getAllByRole("button", { name: /esci/i }).length).toBeGreaterThan(0));
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });
});

describe("App viewer mode", () => {
  it("hides write controls for a viewer", async () => {
    vi.mocked(getMe).mockResolvedValue({ role: "viewer" } as never);
    vi.mocked(getAgents).mockResolvedValue([agent] as never);
    render(<App />);
    // Wait for the viewer dashboard to render (agent name appears), then assert
    // every write control AND the logout button are absent for a viewer.
    await screen.findAllByText("Alpha");
    expect(screen.queryAllByRole("button", { name: /esci/i })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /modifica/i })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /elimina/i })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /nuovo agente/i })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /condividi/i })).toHaveLength(0);
  });

  it("exchanges a hash token on load", async () => {
    window.location.hash = "#tok-xyz";
    vi.mocked(exchangeViewerToken).mockResolvedValue({ role: "viewer" } as never);
    vi.mocked(getMe).mockResolvedValue({ role: "viewer" } as never);
    render(<App />);
    await waitFor(() => expect(exchangeViewerToken).toHaveBeenCalledWith("tok-xyz"));
  });
});

describe("App lifecycle navigation", () => {
  beforeEach(() => {
    vi.mocked(getMe).mockResolvedValue({ role: "viewer" } as never);
    vi.mocked(getAgents).mockResolvedValue([agent] as never);
  });

  it("carica la vista Aperte come predefinita", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Aperte", pressed: true });
    expect(getLifecycles).toHaveBeenCalledWith(1, { state: "open", limit: 50 });
    expect(screen.queryByRole("button", { name: /ordina/i })).not.toBeInTheDocument();
  });

  it("rende il contesto di mercato della raccolta senza animare l'ordine delle righe", async () => {
    const market = { status: "stale", as_of: "2026-07-09T10:20:00Z" } as const;
    const first = { lifecycle_id: "life-1", symbol: "BTCUSDT", status: "open", opened_at: "2026-07-01T00:00:00Z", closed_at: null, last_changed_at: "2026-07-02T00:00:00Z", quantity: "1", exposure_usd: "100", portfolio_weight_pct: "50", held_minutes: null, invested_usd: "100", fees_usd: "1", net_result_usd: "5", net_result_pct: "5", market_series_24h: ["100", "110"] };
    vi.mocked(getLifecycles).mockResolvedValue(lifecyclePage([first], null, market) as never);

    const { container } = render(<App />);

    expect(await screen.findByRole("img", { name: /andamento 24h/i })).toBeInTheDocument();
    expect(screen.getByText(/dato di mercato non aggiornato/i)).toHaveTextContent(market.as_of);
    const row = container.querySelector("tbody tr");
    expect(row?.className).not.toMatch(/(?:transition-(?:all|transform)|animate-)/);
    expect(row?.getAttribute("style")).toBeNull();
  });

  it("keeps selected row order through a poll and restores live order after close", async () => {
    vi.mocked(getLifecycles)
      .mockResolvedValueOnce(lifecyclePage([btc, eth], null) as never)
      .mockResolvedValueOnce(lifecyclePage([ethUpdated, btcUpdated], null) as never);
    vi.useFakeTimers();
    try {
      vi.mocked(getLifecycleDetail).mockResolvedValue(detailBody as never);
      render(<App />);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
      await act(async () => { vi.advanceTimersByTime(15_000); await Promise.resolve(); });
      expect(screen.getAllByRole("button", { name: /Apri dettagli/ })
        .map(button => button.textContent)).toEqual(["BTC", "ETH"]);
      fireEvent.click(screen.getByRole("button", { name: "Chiudi" }));
      expect(screen.getAllByRole("button", { name: /Apri dettagli/ })
        .map(button => button.textContent)).toEqual(["ETH", "BTC"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes with Escape and focuses the first live row when polling removes the selection", async () => {
    vi.mocked(getLifecycles)
      .mockResolvedValueOnce(lifecyclePage([btc, eth], null) as never)
      .mockResolvedValueOnce(lifecyclePage([ethUpdated], null) as never);
    vi.mocked(getLifecycleDetail).mockResolvedValue(detailBody as never);
    vi.useFakeTimers();
    try {
      render(<App />);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole("heading", { name: /Dettaglio BTC/ })).toBeInTheDocument();

      await act(async () => { vi.advanceTimersByTime(15_000); await Promise.resolve(); });
      fireEvent.keyDown(document, { key: "Escape" });

      expect(screen.queryByRole("heading", { name: /Dettaglio BTC/ })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Apri dettagli ETH" })).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a selected open control until Escape reveals its closed row and focuses the table", async () => {
    const closedBtc = lifecycle({
      status: "closed",
      closed_at: "2026-07-14T11:00:00Z",
      quantity: null,
      exposure_usd: null,
      portfolio_weight_pct: null,
      held_minutes: 120,
    });
    vi.mocked(getLifecycles)
      .mockResolvedValueOnce(lifecyclePage([btc], null) as never)
      .mockResolvedValueOnce(lifecyclePage([btc], null) as never)
      .mockResolvedValueOnce(lifecyclePage([closedBtc], null) as never);
    vi.mocked(getLifecycleDetail).mockResolvedValue(detailBody as never);
    vi.useFakeTimers();
    try {
      render(<App />);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "Tutte" }));
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "Apri dettagli BTC" }));
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByRole("heading", { name: /Dettaglio BTC/ })).toBeInTheDocument();

      await act(async () => { vi.advanceTimersByTime(15_000); await Promise.resolve(); });
      expect(screen.getByRole("button", { name: "Apri dettagli BTC" })).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByText("Selezionata")).toBeInTheDocument();
      expect(screen.getByText("Aperta")).toBeInTheDocument();

      fireEvent.keyDown(document, { key: "Escape" });

      expect(screen.queryByRole("heading", { name: /Dettaglio BTC/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Apri dettagli BTC" })).not.toBeInTheDocument();
      expect(screen.getByText("Chiusa")).toBeInTheDocument();
      expect(screen.getByRole("table", { name: "Lifecycle posizioni" })).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes detail when view or agent changes", async () => {
    const beta = { ...agent, id: 2, name: "Beta" };
    vi.mocked(getAgents).mockResolvedValue([agent, beta] as never);
    vi.mocked(getLifecycles).mockResolvedValue(lifecyclePage([btc], null) as never);
    vi.mocked(getLifecycleDetail).mockResolvedValue(detailBody as never);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Apri dettagli BTC" }));
    expect(await screen.findByRole("heading", { name: /Dettaglio BTC/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chiuse" }));
    expect(screen.queryByRole("heading", { name: /Dettaglio BTC/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Aperte" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apri dettagli BTC" }));
    expect(await screen.findByRole("heading", { name: /Dettaglio BTC/ })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Beta"));
    await waitFor(() => expect(screen.queryByRole("heading", { name: /Dettaglio BTC/ })).not.toBeInTheDocument());
  });

  it("returns to login when detail authorization is lost", async () => {
    vi.mocked(getLifecycles).mockResolvedValue(lifecyclePage([btc], null) as never);
    vi.mocked(getLifecycleDetail).mockRejectedValueOnce(new AuthError());
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Apri dettagli BTC" }));
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
  });

  it("cambia a Chiuse e Tutte con una finestra temporale osservabile", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Aperte", pressed: true });

    fireEvent.click(screen.getByRole("button", { name: "Chiuse" }));
    await waitFor(() => expect(getLifecycles).toHaveBeenLastCalledWith(1, expect.objectContaining({
      state: "closed", limit: 50, closedSince: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T00:00:00\.000Z$/),
    })));
    expect(screen.getByLabelText("Dal")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Tutto lo storico" }));
    await waitFor(() => expect(getLifecycles).toHaveBeenLastCalledWith(1, {
      state: "closed", limit: 50, closedSince: "1970-01-01T00:00:00.000Z",
    }));

    fireEvent.click(screen.getByRole("button", { name: "Tutte" }));
    await waitFor(() => expect(getLifecycles).toHaveBeenLastCalledWith(1, {
      state: "all", limit: 50, closedSince: "1970-01-01T00:00:00.000Z",
    }));
  });

  it("carica la pagina successiva concatenando senza duplicare lifecycle", async () => {
    const first = { lifecycle_id: "life-1", symbol: "BTCUSDT", status: "closed", opened_at: "2026-07-01T00:00:00Z", closed_at: "2026-07-02T00:00:00Z", last_changed_at: "2026-07-02T00:00:00Z", quantity: null, exposure_usd: null, portfolio_weight_pct: null, held_minutes: 1440, invested_usd: "100", fees_usd: "1", net_result_usd: "5", net_result_pct: "5" };
    const second = { ...first, lifecycle_id: "life-2", symbol: "ETHUSDT" };
    vi.mocked(getLifecycles)
      .mockResolvedValueOnce(lifecyclePage([], null) as never)
      .mockResolvedValueOnce(lifecyclePage([first], "next-1") as never)
      .mockResolvedValueOnce(lifecyclePage([first, second], null) as never);

    render(<App />);
    await screen.findByRole("button", { name: "Aperte", pressed: true });
    fireEvent.click(screen.getByRole("button", { name: "Chiuse" }));
    await screen.findByText("BTC");
    fireEvent.click(screen.getByRole("button", { name: "Carica altro" }));

    await screen.findByText("ETH");
    expect(screen.getAllByText("BTC")).toHaveLength(1);
    expect(getLifecycles).toHaveBeenLastCalledWith(1, expect.objectContaining({ cursor: "next-1" }));
    expect(screen.queryByRole("button", { name: "Carica altro" })).not.toBeInTheDocument();
  });

  it("serializza Carica altro mentre la pagina è in volo", async () => {
    let resolvePage!: (value: unknown) => void;
    const pendingPage = new Promise((resolve) => { resolvePage = resolve; });
    const first = { lifecycle_id: "life-1", symbol: "BTCUSDT", status: "open", opened_at: "2026-07-01T00:00:00Z", closed_at: null, last_changed_at: "2026-07-02T00:00:00Z", quantity: "1", exposure_usd: "100", portfolio_weight_pct: "50", held_minutes: null, invested_usd: "100", fees_usd: "1", net_result_usd: "5", net_result_pct: "5" };
    vi.mocked(getLifecycles)
      .mockResolvedValueOnce(lifecyclePage([first], "next-1") as never)
      .mockReturnValueOnce(pendingPage as never);

    render(<App />);
    await screen.findByText("BTC");
    const button = screen.getByRole("button", { name: "Carica altro" });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(getLifecycles).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Caricamento…" })).toBeDisabled();
    resolvePage(lifecyclePage([], null));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Caricamento…" })).not.toBeInTheDocument());
  });

  it("riabilita refresh e retry se Carica altro fallisce", async () => {
    const first = { lifecycle_id: "life-1", symbol: "BTCUSDT", status: "open", opened_at: "2026-07-01T00:00:00Z", closed_at: null, last_changed_at: "2026-07-02T00:00:00Z", quantity: "1", exposure_usd: "100", portfolio_weight_pct: "50", held_minutes: null, invested_usd: "100", fees_usd: "1", net_result_usd: "5", net_result_pct: "5" };
    vi.mocked(getLifecycles)
      .mockResolvedValueOnce(lifecyclePage([first], "next-1") as never)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(lifecyclePage([], null) as never);

    render(<App />);
    await screen.findByText("BTC");
    fireEvent.click(screen.getByRole("button", { name: "Carica altro" }));
    await screen.findByRole("button", { name: "Carica altro" });
    fireEvent.click(screen.getByRole("button", { name: "Carica altro" }));

    await waitFor(() => expect(getLifecycles).toHaveBeenCalledTimes(3));
  });

  it("torna al login se la collezione perde l'autorizzazione", async () => {
    vi.mocked(getLifecycles).mockRejectedValueOnce(new AuthError());
    render(<App />);
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
  });
});
