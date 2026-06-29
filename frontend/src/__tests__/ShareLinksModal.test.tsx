import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ShareLinksModal } from "../components/ShareLinksModal";

vi.mock("../api", () => ({
  listShareLinks: vi.fn(),
  createShareLink: vi.fn(),
  revokeShareLink: vi.fn(),
}));
import { listShareLinks, createShareLink, revokeShareLink } from "../api";

beforeEach(() => {
  vi.mocked(listShareLinks).mockReset();
  vi.mocked(createShareLink).mockReset();
  vi.mocked(revokeShareLink).mockReset();
});

const LINK = { id: 1, label: "amici", token: "tok", url: "https://h/#tok", created_at: "" };

describe("ShareLinksModal", () => {
  it("lists existing links with their url", async () => {
    vi.mocked(listShareLinks).mockResolvedValue([LINK] as never);
    render(<ShareLinksModal onClose={() => {}} />);
    expect(await screen.findByDisplayValue("https://h/#tok")).toBeInTheDocument();
  });

  it("creates a link", async () => {
    vi.mocked(listShareLinks).mockResolvedValue([] as never);
    vi.mocked(createShareLink).mockResolvedValue(LINK as never);
    render(<ShareLinksModal onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /crea link/i }));
    await waitFor(() => expect(createShareLink).toHaveBeenCalled());
  });

  it("revokes a link", async () => {
    vi.mocked(listShareLinks).mockResolvedValue([LINK] as never);
    vi.mocked(revokeShareLink).mockResolvedValue(undefined as never);
    render(<ShareLinksModal onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /revoca/i }));
    await waitFor(() => expect(revokeShareLink).toHaveBeenCalledWith(1));
  });
});
