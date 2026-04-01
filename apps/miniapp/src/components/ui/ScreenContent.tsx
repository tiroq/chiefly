import { PAGE_X, PAGE_PT, PAGE_PB } from "./tokens";

interface ScreenContentProps {
  children: React.ReactNode;
  /** Extra bottom padding, e.g. "pb-28" for screens with a floating main button */
  bottomPadding?: string;
  /** Disable default horizontal padding (e.g. for edge-to-edge sections) */
  noPadX?: boolean;
}

/**
 * Standard content wrapper inside Layout.
 * Provides consistent page-level insets so screens never invent their own.
 */
export function ScreenContent({ children, bottomPadding, noPadX }: ScreenContentProps) {
  return (
    <div className={`${noPadX ? "" : PAGE_X} ${PAGE_PT} ${bottomPadding ?? PAGE_PB}`}>
      {children}
    </div>
  );
}
