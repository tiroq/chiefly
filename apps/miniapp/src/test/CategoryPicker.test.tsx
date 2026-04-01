import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CategoryPicker } from "../components/CategoryPicker";

describe("CategoryPicker", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onSelect: vi.fn(),
    currentType: "personal",
    projectName: "My Project",
  };

  it("renders nothing when closed", () => {
    const { container } = render(
      <CategoryPicker {...defaultProps} isOpen={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders project name in header", () => {
    render(<CategoryPicker {...defaultProps} />);
    expect(screen.getByText("My Project")).toBeInTheDocument();
  });

  it("renders all category options", () => {
    render(<CategoryPicker {...defaultProps} />);
    expect(screen.getByText("Personal")).toBeInTheDocument();
    expect(screen.getByText("Family")).toBeInTheDocument();
    expect(screen.getByText("Client")).toBeInTheDocument();
    expect(screen.getByText("Ops")).toBeInTheDocument();
    expect(screen.getByText("Writing")).toBeInTheDocument();
    expect(screen.getByText("Internal")).toBeInTheDocument();
  });

  it("shows checkmark for the current type", () => {
    const { container } = render(
      <CategoryPicker {...defaultProps} currentType="family" />
    );
    // The family button should contain a checkmark SVG
    const buttons = container.querySelectorAll("button");
    const familyButton = Array.from(buttons).find((b) =>
      b.textContent?.includes("Family")
    );
    expect(familyButton).toBeTruthy();
    expect(familyButton?.querySelector("svg")).toBeTruthy();
  });

  it("calls onSelect and onClose when a category is chosen", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <CategoryPicker
        {...defaultProps}
        onSelect={onSelect}
        onClose={onClose}
      />
    );
    // Click the "Ops" option
    const buttons = screen.getAllByRole("button");
    const opsButton = buttons.find((b) => b.textContent?.includes("Ops"));
    expect(opsButton).toBeTruthy();
    fireEvent.click(opsButton!);

    expect(onSelect).toHaveBeenCalledWith("ops");
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when Cancel is clicked", () => {
    const onClose = vi.fn();
    render(<CategoryPicker {...defaultProps} onClose={onClose} />);
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalled();
  });
});
