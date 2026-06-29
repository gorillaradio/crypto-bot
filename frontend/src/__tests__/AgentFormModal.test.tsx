import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentFormModal } from "../components/AgentFormModal";

vi.mock("../api", () => ({
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
}));
import { createAgent, updateAgent } from "../api";

beforeEach(() => {
  vi.mocked(createAgent).mockReset();
  vi.mocked(updateAgent).mockReset();
});

describe("AgentFormModal create", () => {
  it("disables submit until a name is entered", () => {
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
    const submit = screen.getByRole("button", { name: /crea/i });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Alpha" } });
    expect(submit).not.toBeDisabled();
  });

  it("hides model fields when strategy is sma", () => {
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText(/strategia/i), { target: { value: "sma" } });
    expect(screen.queryByLabelText(/provider/i)).not.toBeInTheDocument();
  });

  it("submits the form payload to createAgent", async () => {
    const onSaved = vi.fn();
    vi.mocked(createAgent).mockResolvedValue({ id: 1, name: "Alpha" } as never);
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Alpha" } });
    fireEvent.click(screen.getByRole("button", { name: /crea/i }));
    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createAgent).mock.calls[0][0]).toMatchObject({ name: "Alpha" });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});

describe("AgentFormModal edit", () => {
  it("only allows renaming and calls updateAgent", async () => {
    const onSaved = vi.fn();
    vi.mocked(updateAgent).mockResolvedValue({ id: 2, name: "Renamed" } as never);
    const agent = { id: 2, name: "Old", status: "running", instructions: "",
      cash_usd: "100", equity: "100", return_pct: "0",
      duration_start: "", duration_end: "" };
    render(<AgentFormModal mode="edit" agent={agent} onClose={() => {}} onSaved={onSaved} />);
    expect(screen.queryByLabelText(/strategia/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: /salva/i }));
    await waitFor(() => expect(updateAgent).toHaveBeenCalledWith(2, { name: "Renamed" }));
  });
});
