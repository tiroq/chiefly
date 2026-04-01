import { BADGE_PX, BADGE_PY, BADGE_TEXT, BADGE_RADIUS, BADGE_LG_PX, BADGE_LG_PY, BADGE_LG_TEXT } from "./tokens";

type BadgeSize = "sm" | "lg";

interface BadgeProps {
  children: React.ReactNode;
  colorClass?: string;
  size?: BadgeSize;
  className?: string;
}

/**
 * Non-interactive label pill with two size options.
 *  sm (default) — compact inline badge (kind, confidence)
 *  lg — larger category-style pill (project type)
 */
export function Badge({ children, colorClass = "bg-tg-secondary-bg text-tg-hint", size = "sm", className = "" }: BadgeProps) {
  const px = size === "lg" ? BADGE_LG_PX : BADGE_PX;
  const py = size === "lg" ? BADGE_LG_PY : BADGE_PY;
  const text = size === "lg" ? BADGE_LG_TEXT : BADGE_TEXT;

  return (
    <span className={`${px} ${py} ${text} font-medium ${BADGE_RADIUS} ${colorClass} ${className}`}>
      {children}
    </span>
  );
}
