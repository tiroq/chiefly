import { CARD_PADDING, CARD_RADIUS, CARD_BG } from "./tokens";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  /** Make the card interactive (shows press state) */
  interactive?: boolean;
  onClick?: () => void;
}

/**
 * Standard card container — section-bg with consistent radius and padding.
 */
export function Card({ children, className = "", interactive, onClick }: CardProps) {
  const base = `${CARD_BG} ${CARD_RADIUS} ${CARD_PADDING}`;
  const interactiveStyles = interactive
    ? "active:scale-[0.98] transition-transform cursor-pointer"
    : "";

  if (interactive && onClick) {
    return (
      <div onClick={onClick} className={`${base} ${interactiveStyles} ${className}`}>
        {children}
      </div>
    );
  }

  return <div className={`${base} ${className}`}>{children}</div>;
}
