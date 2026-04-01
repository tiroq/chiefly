import { KindBadge } from "./KindBadge";
import { BottomSheet } from "./ui/BottomSheet";

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
  const context = (
    <>
      <div className="text-xs text-tg-hint">Editing</div>
      <div className="text-sm text-tg-text font-medium truncate">{taskTitle.length > 50 ? taskTitle.substring(0, 50) + "…" : taskTitle}</div>
      <div className="text-xs text-tg-subtitle mt-1">Chiefly is unsure about this task</div>
    </>
  );

  return (
    <BottomSheet isOpen={isOpen} onClose={onClose} title="Choose Interpretation" context={context}>
      <div className="px-2 py-2">
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
    </BottomSheet>
  );
}
