import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ConfirmDeleteModal } from "../components/ConfirmDeleteModal";

vi.mock("../api", () => ({ deleteAgent: vi.fn() }));
import { deleteAgent } from "../api";

const agent = { id: 7, name: "Doomed", status: "running", instructions: "",
  cash_usd: "100", equity: "100", return_pct: "0", duration_start: "", duration_end: "", decision_seconds: 0 };

beforeEach(() => vi.mocked(deleteAgent).mockReset());

describe("ConfirmDeleteModal", () => {
  it("keeps confirm disabled until the exact name is typed", () => {
    render(<ConfirmDeleteModal agent={agent} onClose={() => {}} onDeleted={() => {}} />);
    const confirm = screen.getByRole("button", { name: /elimina/i });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/conferma/i), { target: { value: "Doom" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/conferma/i), { target: { value: "Doomed" } });
    expect(confirm).not.toBeDisabled();
  });

  it("calls deleteAgent and onDeleted on confirm", async () => {
    const onDeleted = vi.fn();
    vi.mocked(deleteAgent).mockResolvedValue(undefined as never);
    render(<ConfirmDeleteModal agent={agent} onClose={() => {}} onDeleted={onDeleted} />);
    fireEvent.change(screen.getByLabelText(/conferma/i), { target: { value: "Doomed" } });
    fireEvent.click(screen.getByRole("button", { name: /elimina/i }));
    await waitFor(() => expect(deleteAgent).toHaveBeenCalledWith(7));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(7));
  });
});
