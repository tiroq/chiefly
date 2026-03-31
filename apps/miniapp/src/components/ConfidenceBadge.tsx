interface ConfidenceBadgeProps {
  confidence: string;
}

export function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const normalized = confidence.toUpperCase();
  
  let colorClass = "bg-tg-secondary-bg text-tg-hint";
  if (normalized === "HIGH") {
    colorClass = "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400";
  } else if (normalized === "MEDIUM") {
    colorClass = "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400";
  } else if (normalized === "LOW") {
    colorClass = "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400";
  }

  return (
    <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${colorClass}`}>
      {normalized}
    </span>
  );
}
