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
  it("keeps submit disabled until name AND model are filled", () => {
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
    const submit = screen.getByRole("button", { name: /crea/i });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Alpha" } });
    expect(submit).toBeDisabled();                              // model still empty
    fireEvent.change(screen.getByLabelText(/modello/i), { target: { value: "claude-opus-4-8" } });
    expect(submit).not.toBeDisabled();
  });

  it("always shows the model field", () => {
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByLabelText(/modello/i)).toBeInTheDocument();
  });

  it("submits the form payload (with model slug) to createAgent", async () => {
    const onSaved = vi.fn();
    vi.mocked(createAgent).mockResolvedValue({ id: 1, name: "Alpha" } as never);
    render(<AgentFormModal mode="create" onClose={() => {}} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Alpha" } });
    fireEvent.change(screen.getByLabelText(/modello/i), { target: { value: "deepseek/deepseek-v4-flash" } });
    fireEvent.click(screen.getByRole("button", { name: /crea/i }));
    await waitFor(() => expect(createAgent).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createAgent).mock.calls[0][0]).toMatchObject({
      name: "Alpha",
      model_name: "deepseek/deepseek-v4-flash",
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});

describe("AgentFormModal edit", () => {
  it("only allows renaming and calls updateAgent", async () => {
    const onSaved = vi.fn();
    vi.mocked(updateAgent).mockResolvedValue({ id: 2, name: "Renamed" } as never);
    const agent = { id: 2, name: "Old", status: "running", instructions: "",
      cash_usd: "100", equity: "100", return_pct: "0",
      duration_start: "", duration_end: "", decision_seconds: 0 };
    render(<AgentFormModal mode="edit" agent={agent} onClose={() => {}} onSaved={onSaved} />);
    expect(screen.queryByLabelText(/modello/i)).not.toBeInTheDocument();   // edit shows name only
    fireEvent.change(screen.getByLabelText(/nome/i), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: /salva/i }));
    await waitFor(() => expect(updateAgent).toHaveBeenCalledWith(2, { name: "Renamed" }));
  });
});
