import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ScreenContent } from "../components/ui/ScreenContent";
import { Card } from "../components/ui/Card";
import { Chip } from "../components/ui/Chip";
import { Badge } from "../components/ui/Badge";
import { ListRow } from "../components/ui/ListRow";
import { SectionHeader } from "../components/ui/SectionHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { BottomSheet } from "../components/ui/BottomSheet";

describe("ScreenContent", () => {
  it("applies default page insets", () => {
    const { container } = render(<ScreenContent>Hello</ScreenContent>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("px-4");
    expect(el.className).toContain("pt-4");
    expect(el.className).toContain("pb-6");
  });

  it("accepts custom bottomPadding", () => {
    const { container } = render(
      <ScreenContent bottomPadding="pb-28">Hello</ScreenContent>
    );
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("pb-28");
    expect(el.className).not.toContain("pb-6");
  });

  it("removes horizontal padding with noPadX", () => {
    const { container } = render(
      <ScreenContent noPadX>Hello</ScreenContent>
    );
    const el = container.firstChild as HTMLElement;
    expect(el.className).not.toContain("px-4");
  });
});

describe("Card", () => {
  it("renders with standard bg, radius, and padding", () => {
    const { container } = render(<Card>Content</Card>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("bg-tg-section-bg");
    expect(el.className).toContain("rounded-2xl");
    expect(el.className).toContain("p-4");
  });

  it("is interactive when onClick is provided", () => {
    const onClick = vi.fn();
    const { container } = render(
      <Card interactive onClick={onClick}>Click me</Card>
    );
    fireEvent.click(container.firstChild as HTMLElement);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("applies custom className", () => {
    const { container } = render(<Card className="!p-3">Smaller</Card>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("!p-3");
  });
});

describe("Chip", () => {
  it("renders as a button", () => {
    render(<Chip>All</Chip>);
    expect(screen.getByRole("button")).toHaveTextContent("All");
  });

  it("applies selected styles", () => {
    const { container } = render(<Chip selected>Selected</Chip>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("bg-tg-button");
    expect(el.className).toContain("text-tg-button-text");
  });

  it("applies unselected styles", () => {
    const { container } = render(<Chip>Unselected</Chip>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("bg-tg-secondary-bg");
  });

  it("fires onClick", () => {
    const onClick = vi.fn();
    render(<Chip onClick={onClick}>Click</Chip>);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("Badge", () => {
  it("renders default size with sm tokens", () => {
    const { container } = render(<Badge>label</Badge>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("px-2.5");
    expect(el.className).toContain("py-1");
    expect(el.className).toContain("text-[11px]");
  });

  it("renders lg size with larger tokens", () => {
    const { container } = render(<Badge size="lg">big</Badge>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("px-3");
    expect(el.className).toContain("py-1.5");
    expect(el.className).toContain("text-xs");
  });

  it("accepts a custom colorClass", () => {
    const { container } = render(
      <Badge colorClass="bg-red-500 text-white">custom</Badge>
    );
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("bg-red-500");
  });
});

describe("ListRow", () => {
  it("renders with border by default", () => {
    const { container } = render(<ListRow>Row</ListRow>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain("border-b");
    expect(el.className).toContain("min-h-[48px]");
  });

  it("removes border when border=false", () => {
    const { container } = render(<ListRow border={false}>Row</ListRow>);
    const el = container.firstChild as HTMLElement;
    expect(el.className).not.toContain("border-b");
  });

  it("is interactive when onClick is provided", () => {
    const onClick = vi.fn();
    const { container } = render(<ListRow onClick={onClick}>Click</ListRow>);
    fireEvent.click(container.firstChild as HTMLElement);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("SectionHeader", () => {
  it("renders an h2 with the label", () => {
    render(<SectionHeader>Queue</SectionHeader>);
    const el = screen.getByText("Queue");
    expect(el.tagName).toBe("H2");
    expect(el.className).toContain("uppercase");
  });
});

describe("EmptyState", () => {
  it("renders title and default icon", () => {
    render(<EmptyState title="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("✦")).toBeInTheDocument();
  });

  it("renders custom icon and subtitle", () => {
    render(<EmptyState icon="📭" title="Empty" subtitle="Sub" />);
    expect(screen.getByText("📭")).toBeInTheDocument();
    expect(screen.getByText("Sub")).toBeInTheDocument();
  });

  it("renders action slot", () => {
    render(
      <EmptyState title="Empty" action={<button>Retry</button>} />
    );
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});

describe("BottomSheet", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <BottomSheet isOpen={false} onClose={vi.fn()} title="Test">
        content
      </BottomSheet>
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders title and content when open", () => {
    render(
      <BottomSheet isOpen={true} onClose={vi.fn()} title="Pick One">
        <div>option A</div>
      </BottomSheet>
    );
    expect(screen.getByText("Pick One")).toBeInTheDocument();
    expect(screen.getByText("option A")).toBeInTheDocument();
  });

  it("renders context when provided", () => {
    render(
      <BottomSheet
        isOpen={true}
        onClose={vi.fn()}
        title="Sheet"
        context={<div>Context info</div>}
      >
        body
      </BottomSheet>
    );
    expect(screen.getByText("Context info")).toBeInTheDocument();
  });

  it("calls onClose when Cancel is clicked", () => {
    const onClose = vi.fn();
    render(
      <BottomSheet isOpen={true} onClose={onClose} title="Sheet">
        body
      </BottomSheet>
    );
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when backdrop is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(
      <BottomSheet isOpen={true} onClose={onClose} title="Sheet">
        body
      </BottomSheet>
    );
    // Click the backdrop (outermost overlay div)
    fireEvent.click(container.firstChild as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
