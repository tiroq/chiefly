interface EmptyStateProps {
  icon?: string;
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

/**
 * Centered empty-state placeholder — consistent across screens.
 */
export function EmptyState({ icon = "✦", title, subtitle, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="text-4xl mb-3 text-tg-hint">{icon}</div>
      <div className="text-base font-medium text-tg-text">{title}</div>
      {subtitle && <div className="text-sm text-tg-hint mt-1">{subtitle}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
