import { ROW_PX, ROW_PY, ROW_MIN_H } from "./tokens";

interface ListRowProps {
  children: React.ReactNode;
  /** Show bottom border (default: true). Last row in a group should pass false. */
  border?: boolean;
  onClick?: () => void;
}

/**
 * Standard list row inside a Card — consistent padding and 48px min touch height.
 */
export function ListRow({ children, border = true, onClick }: ListRowProps) {
  const borderClass = border ? "border-b border-tg-secondary-bg" : "";
  const interactive = onClick
    ? "active:bg-tg-secondary-bg transition-colors cursor-pointer"
    : "";

  return (
    <div
      onClick={onClick}
      className={`flex items-center justify-between ${ROW_PX} ${ROW_PY} ${ROW_MIN_H} bg-tg-section-bg ${borderClass} ${interactive}`}
    >
      {children}
    </div>
  );
}
