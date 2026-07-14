import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthError, getLifecycleDetail, type LifecycleDetail } from "../api";
import { OpenLifecycleDetail } from "../components/OpenLifecycleDetail";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, getLifecycleDetail: vi.fn() };
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

const detail = (over: Partial<LifecycleDetail> = {}): LifecycleDetail => ({
  lifecycle_id: "life-1",
  cycle_id: "hold",
  symbol: "BTCUSDT",
  status: "open",
  opened_at: "2026-07-14T09:00:00Z",
  last_changed_at: "2026-07-14T10:00:00Z",
  evaluation: {
    action: "HOLD",
    rationale: "thesis intact",
    cycle_id: "hold",
    timestamp: "2026-07-14T10:00:00Z",
    policy_refs: ["P003"],
    policy_alignment: "follows",
    override_reason: "",
  },
  economy: {
    quantity: "0.6",
    avg_price: "100",
    last_price: "130",
    exposure_usd: "78",
    invested_usd: "100",
    realized_usd: "8",
    unrealized_usd: "18",
    fees_usd: "0.148",
    net_result_usd: "25.852",
    net_result_pct: "25.852",
  },
  market: { status: "fresh", as_of: "2026-07-14T10:00:00Z" },
  trades: [{
    id: 1,
    cycle_id: "open",
    side: "BUY",
    quantity: "1",
    price: "100",
    fee: "0.1",
    timestamp: "2026-07-14T09:00:00Z",
  }],
  ...over,
});

describe("OpenLifecycleDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps loading and errors local and retries the same lifecycle", async () => {
    vi.mocked(getLifecycleDetail)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(detail());

    render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={vi.fn()}
        onAuthLost={vi.fn()}
      />,
    );

    expect(screen.getByText("Caricamento dettaglio…")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Riprova" }));
    expect(await screen.findByRole("heading", { name: /BTC/ })).toBeInTheDocument();
    expect(getLifecycleDetail).toHaveBeenLastCalledWith(1, "life-1");
  });

  it("declares the absence of an explicit evaluation without inference", async () => {
    vi.mocked(getLifecycleDetail).mockResolvedValue(detail({ evaluation: null }));

    render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={vi.fn()}
        onAuthLost={vi.fn()}
      />,
    );

    expect(await screen.findByText("Nessuna valutazione esplicita registrata")).toBeInTheDocument();
  });

  it("ignores a late response from the previous selection", async () => {
    const first = deferred<LifecycleDetail>();
    vi.mocked(getLifecycleDetail)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(detail({ lifecycle_id: "life-2", symbol: "ETHUSDT" }));

    const view = render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={vi.fn()}
        onAuthLost={vi.fn()}
      />,
    );
    view.rerender(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-2"
        onClose={vi.fn()}
        onAuthLost={vi.fn()}
      />,
    );

    expect(await screen.findByRole("heading", { name: /ETH/ })).toBeInTheDocument();
    await act(async () => {
      first.resolve(detail({ symbol: "BTCUSDT" }));
      await first.promise;
    });
    expect(screen.getByRole("heading", { name: /ETH/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /BTC/ })).not.toBeInTheDocument();
  });

  it("renders explicit evaluation, net breakdown, market disclosure and collapsed accounting", async () => {
    vi.mocked(getLifecycleDetail).mockResolvedValue(detail());

    render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={vi.fn()}
        onAuthLost={vi.fn()}
      />,
    );

    expect(await screen.findByText("thesis intact")).toBeInTheDocument();
    expect(screen.getByText("P003")).toBeInTheDocument();
    expect(screen.getByText(/^realizzato$/i)).toBeInTheDocument();
    expect(screen.getByText(/^non realizzato$/i)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Economia" })).getByText("Fee")).toBeInTheDocument();
    expect(screen.getByText("Dati di mercato aggiornati.")).toBeInTheDocument();
    const accounting = screen.getByText("Contabilità").closest("details");
    expect(accounting).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Contabilità"));
    expect(screen.getByText(/BUY/)).toBeInTheDocument();
  });

  it("closes with Escape and focuses the detail heading after load", async () => {
    const onClose = vi.fn();
    vi.mocked(getLifecycleDetail).mockResolvedValue(detail());

    render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={onClose}
        onAuthLost={vi.fn()}
      />,
    );

    const heading = await screen.findByRole("heading", { name: /BTC/ });
    await waitFor(() => expect(heading).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("masks market-derived amounts when market data is unavailable but keeps accounting", async () => {
    vi.mocked(getLifecycleDetail).mockResolvedValue(detail({
      market: { status: "unavailable", as_of: null },
    }));

    render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={vi.fn()}
        onAuthLost={vi.fn()}
      />,
    );

    expect(await screen.findByText("Dati di mercato non disponibili.")).toBeInTheDocument();
    const economy = screen.getByRole("region", { name: "Economia" });
    expect(within(economy).getByText("Risultato netto").nextElementSibling).toHaveTextContent("—");
    expect(within(economy).getByText("Esposizione").nextElementSibling).toHaveTextContent("—");
    expect(within(economy).getByText("Fee").nextElementSibling).toHaveTextContent("$0.15");
    fireEvent.click(screen.getByText("Contabilità"));
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("$0.10")).toBeInTheDocument();
  });

  it("reports auth loss globally without rendering a local retry", async () => {
    const onAuthLost = vi.fn();
    vi.mocked(getLifecycleDetail).mockRejectedValue(new AuthError());

    render(
      <OpenLifecycleDetail
        agentId={1}
        lifecycleId="life-1"
        onClose={vi.fn()}
        onAuthLost={onAuthLost}
      />,
    );

    await waitFor(() => expect(onAuthLost).toHaveBeenCalledOnce());
    expect(screen.queryByRole("button", { name: "Riprova" })).not.toBeInTheDocument();
  });
});
