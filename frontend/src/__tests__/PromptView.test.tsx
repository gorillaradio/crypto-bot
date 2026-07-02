import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PromptView } from "../components/PromptPanel";
import type { PromptPreview } from "../api";

const preview: PromptPreview = {
  decision: { system: "SYS-DECISION", user: "USER-DECISION" },
  reflection: { system: "SYS-REFLECT", user: "USER-REFLECT", note: "nota reflection" },
  retry: { system: "SYS-DECISION", user: "USER-RETRY" },
};

describe("PromptView", () => {
  it("shows the decision prompt by default", () => {
    render(<PromptView preview={preview} />);
    expect(screen.getByText("SYS-DECISION")).toBeInTheDocument();
    expect(screen.getByText("USER-DECISION")).toBeInTheDocument();
  });

  it("switches to reflection and shows its note", () => {
    render(<PromptView preview={preview} />);
    fireEvent.click(screen.getByRole("button", { name: "Reflection" }));
    expect(screen.getByText("USER-REFLECT")).toBeInTheDocument();
    expect(screen.getByText("nota reflection")).toBeInTheDocument();
  });
});
