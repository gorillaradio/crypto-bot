import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BrainBadge } from "../components/BrainBadge";

describe("BrainBadge", () => {
  it("labels the brain version", () => {
    render(<BrainBadge version="v2" />);
    expect(screen.getByText("brain v2")).toBeInTheDocument();
  });
});
