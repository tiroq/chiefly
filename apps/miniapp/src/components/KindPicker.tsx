import { KindBadge } from "./KindBadge";

interface KindPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (kind: string) => void;
  currentKind: string;
  taskTitle: string;
}

const KINDS = [
  { id: "task", desc: "Actionable item with a clear next step" },
  { id: "waiting", desc: "Blocked on someone else" },
  { id: "commitment", desc: "Time-bound event or meeting" },
  { id: "idea", desc: "Thought to explore later" },
  { id: "reference", desc: "Information to keep" },
];

export function KindPicker({ isOpen, onClose, onSelect, currentKind, taskTitle }: KindPickerProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/50 transition-opacity">
      <div className="w-full bg-tg-section-bg rounded-t-2xl max-h-[80vh] flex flex-col pb-safe">
        <div className="w-10 h-1 bg-tg-hint/30 rounded-full mx-auto mt-3 mb-1" />
        
        <div className="px-4 pt-1 pb-2">
          <div className="text-xs text-tg-hint">Editing</div>
          <div className="text-sm text-tg-text font-medium truncate">{taskTitle.length > 50 ? taskTitle.substring(0, 50) + "…" : taskTitle}</div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-xs text-tg-subtitle">Current:</span>
            <KindBadge kind={currentKind} />
          </div>
        </div>

        <div className="flex justify-between items-center p-4 border-b border-tg-secondary-bg">
          <h2 className="text-lg font-semibold text-tg-text">Select Type</h2>
          <button onClick={onClose} className="text-sm font-medium text-tg-hint active:text-tg-text transition-colors">
            Cancel
          </button>
        </div>
        
        <div className="overflow-y-auto p-2">
          <div className="flex flex-col gap-1">
            {KINDS.map((kind) => (
              <button
                key={kind.id}
                onClick={() => {
                  onSelect(kind.id);
                  onClose();
                }}
                className={`flex items-center justify-between p-3.5 rounded-xl text-left transition-colors ${
                  currentKind === kind.id ? "bg-tg-secondary-bg" : "active:bg-tg-secondary-bg"
                }`}
              >
                <div>
                  <div className="mb-1">
                    <KindBadge kind={kind.id} />
                  </div>
                  <div className="text-sm text-tg-subtitle">{kind.desc}</div>
                </div>
                {currentKind === kind.id && (
                  <svg className="w-5 h-5 text-tg-link" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
