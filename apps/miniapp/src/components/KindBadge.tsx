import { Badge } from "./ui/Badge";

interface KindBadgeProps {
  kind: string;
}

const KIND_COLORS: Record<string, string> = {
  TASK: "bg-blue-500/15 text-blue-400",
  WAITING: "bg-purple-500/15 text-purple-400",
  COMMITMENT: "bg-orange-500/15 text-orange-400",
  IDEA: "bg-yellow-500/15 text-yellow-400",
  REFERENCE: "bg-tg-hint/20 text-tg-hint",
};

export function KindBadge({ kind }: KindBadgeProps) {
  const normalized = kind.toUpperCase();
  const colorClass = KIND_COLORS[normalized] ?? "bg-tg-secondary-bg text-tg-hint";

  return <Badge colorClass={colorClass}>{normalized}</Badge>;
}
