import { KindBadge } from "./KindBadge";

interface AmbiguityPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (index: number) => void;
  ambiguities: string[];
  options: Record<string, unknown>[];
  taskTitle: string;
  clarifyingIdx: number | null;
}

export function AmbiguityPicker({ isOpen, onClose, onSelect, ambiguities, options, taskTitle, clarifyingIdx }: AmbiguityPickerProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/50 transition-opacity">
      <div className="w-full bg-tg-section-bg rounded-t-2xl max-h-[80vh] flex flex-col pb-safe">
        {/* Drag handle */}
        <div className="w-10 h-1 bg-tg-hint/30 rounded-full mx-auto mt-3 mb-1" />
        
        {/* Context header */}
        <div className="px-4 pt-1 pb-2">
          <div className="text-xs text-tg-hint">Editing</div>
          <div className="text-sm text-tg-text font-medium truncate">{taskTitle.length > 50 ? taskTitle.substring(0, 50) + "…" : taskTitle}</div>
          <div className="text-xs text-tg-subtitle mt-1">Chiefly is unsure about this task</div>
        </div>
        
        {/* Header */}
        <div className="flex justify-between items-center p-4 border-b border-tg-secondary-bg">
          <h2 className="text-lg font-semibold text-tg-text">Choose Interpretation</h2>
          <button onClick={onClose} className="text-sm font-medium text-tg-hint active:text-tg-text transition-colors">
            Cancel
          </button>
        </div>
        
        {/* Content */}
        <div className="overflow-y-auto p-4">
          {/* Ambiguity strings */}
          {ambiguities.length > 0 && (
            <div className="bg-amber-500/10 rounded-2xl p-3 mb-4">
              <ul className="space-y-1">
                {ambiguities.map((amb, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-amber-600 dark:text-amber-400">
                    <svg className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>{amb}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          
          {/* Option cards */}
          <div className="flex flex-col gap-2">
            {options.map((opt, idx) => (
              <button
                key={idx}
                onClick={() => onSelect(idx)}
                disabled={clarifyingIdx !== null}
                className="w-full text-left bg-tg-secondary-bg rounded-xl p-3.5 active:bg-tg-bg transition-colors"
              >
                {clarifyingIdx === idx ? (
                  <div className="flex justify-center py-3">
                    <div className="w-5 h-5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
                  </div>
                ) : (
                  <>
                    <div className="mb-1.5">
                      <KindBadge kind={String(opt.type || opt.kind || "TASK")} />
                    </div>
                    <div className="font-medium text-tg-text text-sm">{String(opt.title || `Option ${idx + 1}`)}</div>
                    {opt.reason && (
                      <div className="text-xs text-tg-hint mt-1">{String(opt.reason)}</div>
                    )}
                  </>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
