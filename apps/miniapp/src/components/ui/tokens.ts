/**
 * Design tokens for the Chiefly Mini App layout system.
 *
 * These are Tailwind class fragments used by shared primitives.
 * Centralizing them here means a spacing change propagates everywhere.
 */

/* ── Page-level ────────────────────────────────────────── */
/** Horizontal inset for all screen content */
export const PAGE_X = "px-4";          // 16px

/** Vertical padding at the top of screen content */
export const PAGE_PT = "pt-4";         // 16px

/** Vertical padding at the bottom of screen content */
export const PAGE_PB = "pb-6";         // 24px — breathing room above safe-area

/* ── Section ───────────────────────────────────────────── */
/** Vertical gap between top-level sections */
export const SECTION_GAP = "gap-6";    // 24px

/** Gap between items inside a section (cards in a list) */
export const ITEM_GAP = "gap-3";       // 12px

/* ── Card ──────────────────────────────────────────────── */
export const CARD_PADDING = "p-4";     // 16px
export const CARD_RADIUS = "rounded-2xl";
export const CARD_BG = "bg-tg-section-bg";

/* ── ListRow ───────────────────────────────────────────── */
export const ROW_PX = "px-4";          // 16px
export const ROW_PY = "py-3.5";        // 14px — comfortably tappable
export const ROW_MIN_H = "min-h-[48px]"; // 48px touch target

/* ── Chip (interactive filter pill) ────────────────────── */
export const CHIP_PX = "px-4";         // 16px
export const CHIP_PY = "py-2";         // 8px
export const CHIP_TEXT = "text-sm";
export const CHIP_RADIUS = "rounded-full";
export const CHIP_MIN_H = "min-h-[36px]"; // 36px touch target

/* ── Badge (non-interactive label pill) ────────────────── */
export const BADGE_PX = "px-2.5";      // 10px
export const BADGE_PY = "py-1";        // 4px
export const BADGE_TEXT = "text-[11px]";
export const BADGE_RADIUS = "rounded-full";

/* ── Large badge (project type / category pills) ──────── */
export const BADGE_LG_PX = "px-3";     // 12px
export const BADGE_LG_PY = "py-1.5";   // 6px
export const BADGE_LG_TEXT = "text-xs"; // 12px
