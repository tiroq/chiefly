interface ConfidenceBadgeProps {
  confidence: string;
}

export function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const normalized = confidence.toUpperCase();
  
  let colorClass = "bg-tg-secondary-bg text-tg-hint";
  if (normalized === "HIGH") {
    colorClass = "bg-green-500/15 text-green-400";
  } else if (normalized === "MEDIUM") {
    colorClass = "bg-amber-500/15 text-amber-400";
  } else if (normalized === "LOW") {
    colorClass = "bg-red-500/15 text-red-400";
  }

  return (
    <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${colorClass}`}>
      {normalized}
    </span>
  );
}
