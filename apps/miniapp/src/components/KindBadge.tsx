interface KindBadgeProps {
  kind: string;
}

export function KindBadge({ kind }: KindBadgeProps) {
  const normalized = kind.toUpperCase();
  
  let colorClass = "bg-tg-secondary-bg text-tg-hint";
  if (normalized === "TASK") {
    colorClass = "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400";
  } else if (normalized === "WAITING") {
    colorClass = "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400";
  } else if (normalized === "COMMITMENT") {
    colorClass = "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400";
  } else if (normalized === "IDEA") {
    colorClass = "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400";
  } else if (normalized === "REFERENCE") {
    colorClass = "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
  }

  return (
    <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${colorClass}`}>
      {normalized}
    </span>
  );
}
