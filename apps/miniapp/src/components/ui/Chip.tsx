import { CHIP_PX, CHIP_PY, CHIP_TEXT, CHIP_RADIUS, CHIP_MIN_H } from "./tokens";

interface ChipProps {
  children: React.ReactNode;
  selected?: boolean;
  onClick?: () => void;
}

/**
 * Touch-friendly filter chip — used for queue filter tabs and similar controls.
 */
export function Chip({ children, selected, onClick }: ChipProps) {
  const colorClass = selected
    ? "bg-tg-button text-tg-button-text"
    : "bg-tg-secondary-bg text-tg-hint active:bg-tg-secondary-bg/80";

  return (
    <button
      onClick={onClick}
      className={`flex items-center whitespace-nowrap ${CHIP_PX} ${CHIP_PY} ${CHIP_RADIUS} ${CHIP_TEXT} ${CHIP_MIN_H} font-medium transition-colors ${colorClass}`}
    >
      {children}
    </button>
  );
}
