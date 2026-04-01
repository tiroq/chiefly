interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  /** Optional context block shown above the title bar */
  context?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Shared bottom-sheet modal — drag handle, context, title bar, scrollable content.
 * Replaces the duplicated sheet chrome in all picker components.
 */
export function BottomSheet({ isOpen, onClose, title, context, children }: BottomSheetProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end bg-black/50 transition-opacity"
      onClick={onClose}
    >
      <div
        className="w-full bg-tg-section-bg rounded-t-2xl max-h-[80vh] flex flex-col pb-safe"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drag handle */}
        <div className="w-10 h-1 bg-tg-hint/30 rounded-full mx-auto mt-3 mb-1" />

        {/* Optional context header */}
        {context && <div className="px-4 pt-1 pb-2">{context}</div>}

        {/* Title bar */}
        <div className="flex justify-between items-center px-4 pb-3 pt-1 border-b border-tg-secondary-bg">
          <h2 className="text-lg font-semibold text-tg-text">{title}</h2>
          <button
            onClick={onClose}
            className="text-sm font-medium text-tg-hint active:text-tg-text transition-colors"
          >
            Cancel
          </button>
        </div>

        {/* Scrollable content */}
        <div className="overflow-y-auto p-2">
          {children}
        </div>
      </div>
    </div>
  );
}
