interface KindBadgeProps {
  kind: string;
}

export function KindBadge({ kind }: KindBadgeProps) {
  const normalized = kind.toUpperCase();
  
  let colorClass = "bg-tg-secondary-bg text-tg-hint";
  if (normalized === "TASK") {
    colorClass = "bg-blue-500/15 text-blue-400";
  } else if (normalized === "WAITING") {
    colorClass = "bg-purple-500/15 text-purple-400";
  } else if (normalized === "COMMITMENT") {
    colorClass = "bg-orange-500/15 text-orange-400";
  } else if (normalized === "IDEA") {
    colorClass = "bg-yellow-500/15 text-yellow-400";
  } else if (normalized === "REFERENCE") {
    colorClass = "bg-tg-hint/20 text-tg-hint";
  }

  return (
    <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${colorClass}`}>
      {normalized}
    </span>
  );
}
