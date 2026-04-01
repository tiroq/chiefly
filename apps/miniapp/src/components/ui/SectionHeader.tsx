interface SectionHeaderProps {
  children: React.ReactNode;
}

/**
 * Shared section header label — e.g. "Queue", "Display", "Features".
 */
export function SectionHeader({ children }: SectionHeaderProps) {
  return (
    <h2 className="text-xs font-medium text-tg-hint uppercase tracking-wide mb-2">
      {children}
    </h2>
  );
}
