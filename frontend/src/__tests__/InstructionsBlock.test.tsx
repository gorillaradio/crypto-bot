import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, afterEach } from "vitest";
import { InstructionsBlock } from "../components/InstructionsBlock";

// jsdom doesn't lay out, so scrollHeight/clientHeight are 0. Force an overflow
// so the collapse toggle becomes relevant.
function forceOverflow(scroll: number, client: number) {
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, value: scroll });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: client });
}

afterEach(() => {
  // @ts-expect-error restore to default getter
  delete HTMLElement.prototype.scrollHeight;
  // @ts-expect-error restore to default getter
  delete HTMLElement.prototype.clientHeight;
});

describe("InstructionsBlock", () => {
  it("hides the toggle when the text fits", () => {
    forceOverflow(40, 40);
    render(<InstructionsBlock text="breve" />);
    expect(screen.queryByText(/mostra/i)).toBeNull();
  });

  it("offers 'mostra di più' when the text overflows and expands on click", () => {
    forceOverflow(120, 40);
    render(<InstructionsBlock text="riga molto lunga che va a capo" />);
    const toggle = screen.getByRole("button", { name: /mostra di più/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent(/mostra meno/i);
    expect(document.querySelector(".instructions-text")).toHaveClass("open");
  });
});
