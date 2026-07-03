import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "../App";

vi.mock("../api", () => ({
  AuthError: class AuthError extends Error {},
  getMe: vi.fn(),
  getAgents: vi.fn(),
  getEquity: vi.fn(() => Promise.resolve([])),
  getBenchmarks: vi.fn(() => Promise.resolve([])),
  getAgentMetrics: vi.fn(() => Promise.resolve(null)),
  getEvents: vi.fn(() => Promise.resolve([])),
  getPositions: vi.fn(() => Promise.resolve([])),
  getMemory: vi.fn(() => Promise.resolve(null)),
  getPrompt: vi.fn(() => Promise.resolve(null)),
  logout: vi.fn(() => Promise.resolve()),
  exchangeViewerToken: vi.fn(),
  getKlines: vi.fn(() => Promise.resolve([])),
}));
import { getMe, getAgents, exchangeViewerToken } from "../api";

beforeEach(() => {
  vi.mocked(getAgents).mockResolvedValue([] as never);
  vi.mocked(getMe).mockReset();
  vi.mocked(exchangeViewerToken).mockReset();
  window.location.hash = "";
});

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
    vi.mocked(getAgents).mockResolvedValue([{
      id: 1, name: "Alpha", status: "running", instructions: "",
      cash_usd: "100", equity: "100", return_pct: "0",
      duration_start: new Date().toISOString(), duration_end: new Date().toISOString(),
    }] as never);
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
