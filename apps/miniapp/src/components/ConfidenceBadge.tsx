import { Badge } from "./ui/Badge";

interface ConfidenceBadgeProps {
  confidence: string;
}

const CONFIDENCE_COLORS: Record<string, string> = {
  HIGH: "bg-green-500/15 text-green-400",
  MEDIUM: "bg-amber-500/15 text-amber-400",
  LOW: "bg-red-500/15 text-red-400",
};

export function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const normalized = confidence.toUpperCase();
  const colorClass = CONFIDENCE_COLORS[normalized] ?? "bg-tg-secondary-bg text-tg-hint";

  return <Badge colorClass={colorClass}>{normalized}</Badge>;
}
