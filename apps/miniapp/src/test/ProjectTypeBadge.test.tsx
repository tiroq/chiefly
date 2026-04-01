import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProjectTypeBadge } from "../components/ProjectTypeBadge";

describe("ProjectTypeBadge", () => {
  it("renders the project type label with capitalization", () => {
    render(<ProjectTypeBadge projectType="personal" />);
    expect(screen.getByText("Personal")).toBeInTheDocument();
  });

  it("renders with color-coded styling for known types", () => {
    const { container } = render(<ProjectTypeBadge projectType="family" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.tagName).toBe("SPAN");
    expect(badge.className).toContain("rounded-full");
    expect(badge.className).toContain("px-3");
    expect(badge.className).toContain("py-1");
  });

  it("renders as a button with chevron when interactive", () => {
    const onClick = () => {};
    render(<ProjectTypeBadge projectType="client" interactive onClick={onClick} />);
    const button = screen.getByRole("button");
    expect(button).toBeInTheDocument();
    expect(button.textContent).toContain("Client");
    // Has chevron SVG
    expect(button.querySelector("svg")).toBeTruthy();
  });

  it("renders as a span when not interactive", () => {
    render(<ProjectTypeBadge projectType="ops" />);
    const el = screen.getByText("Ops");
    expect(el.tagName).toBe("SPAN");
  });

  it("handles unknown project types gracefully", () => {
    render(<ProjectTypeBadge projectType="unknown_type" />);
    expect(screen.getByText("Unknown_type")).toBeInTheDocument();
  });
});
