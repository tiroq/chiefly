import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KindBadge } from "../components/KindBadge";
import { ConfidenceBadge } from "../components/ConfidenceBadge";

describe("KindBadge", () => {
  it("renders the kind label uppercased", () => {
    render(<KindBadge kind="task" />);
    expect(screen.getByText("TASK")).toBeInTheDocument();
  });

  it("applies updated padding classes", () => {
    const { container } = render(<KindBadge kind="idea" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("px-2.5");
    expect(badge.className).toContain("py-1");
    expect(badge.className).toContain("text-[11px]");
  });

  it("applies color class for known kinds", () => {
    const { container } = render(<KindBadge kind="waiting" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("text-purple-400");
  });
});

describe("ConfidenceBadge", () => {
  it("renders the confidence label uppercased", () => {
    render(<ConfidenceBadge confidence="high" />);
    expect(screen.getByText("HIGH")).toBeInTheDocument();
  });

  it("applies updated padding classes", () => {
    const { container } = render(<ConfidenceBadge confidence="medium" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("px-2.5");
    expect(badge.className).toContain("py-1");
    expect(badge.className).toContain("text-[11px]");
  });
});
