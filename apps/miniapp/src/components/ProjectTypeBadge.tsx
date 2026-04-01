interface ProjectTypeBadgeProps {
  projectType: string;
  interactive?: boolean;
  onClick?: () => void;
}

export function ProjectTypeBadge({ projectType, interactive, onClick }: ProjectTypeBadgeProps) {
  const normalized = projectType.toLowerCase();

  let colorClass = "bg-tg-secondary-bg text-tg-hint";
  if (normalized === "personal") {
    colorClass = "bg-blue-500/15 text-blue-400";
  } else if (normalized === "family") {
    colorClass = "bg-pink-500/15 text-pink-400";
  } else if (normalized === "client") {
    colorClass = "bg-green-500/15 text-green-400";
  } else if (normalized === "ops") {
    colorClass = "bg-orange-500/15 text-orange-400";
  } else if (normalized === "writing") {
    colorClass = "bg-purple-500/15 text-purple-400";
  } else if (normalized === "internal") {
    colorClass = "bg-amber-500/15 text-amber-400";
  }

  const label = normalized.charAt(0).toUpperCase() + normalized.slice(1);

  if (interactive && onClick) {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-full ${colorClass} active:opacity-70 transition-opacity`}
      >
        {label}
        <svg className="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
    );
  }

  return (
    <span className={`px-3 py-1 text-xs font-medium rounded-full ${colorClass}`}>
      {label}
    </span>
  );
}
