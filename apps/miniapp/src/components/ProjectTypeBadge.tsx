import { Badge } from "./ui/Badge";
import { BADGE_LG_PX, BADGE_LG_PY, BADGE_LG_TEXT, BADGE_RADIUS } from "./ui/tokens";

interface ProjectTypeBadgeProps {
  projectType: string;
  interactive?: boolean;
  onClick?: () => void;
}

const TYPE_COLORS: Record<string, string> = {
  personal: "bg-blue-500/15 text-blue-400",
  family: "bg-pink-500/15 text-pink-400",
  client: "bg-green-500/15 text-green-400",
  ops: "bg-orange-500/15 text-orange-400",
  writing: "bg-purple-500/15 text-purple-400",
  internal: "bg-amber-500/15 text-amber-400",
};

export function ProjectTypeBadge({ projectType, interactive, onClick }: ProjectTypeBadgeProps) {
  const normalized = projectType.toLowerCase();
  const colorClass = TYPE_COLORS[normalized] ?? "bg-tg-secondary-bg text-tg-hint";
  const label = normalized.charAt(0).toUpperCase() + normalized.slice(1);

  if (interactive && onClick) {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        className={`inline-flex items-center gap-1 ${BADGE_LG_PX} ${BADGE_LG_PY} ${BADGE_LG_TEXT} font-medium ${BADGE_RADIUS} ${colorClass} active:opacity-70 transition-opacity`}
      >
        {label}
        <svg className="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
    );
  }

  return <Badge colorClass={colorClass} size="lg">{label}</Badge>;
}
