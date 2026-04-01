import { KindBadge } from "./KindBadge";
import { BottomSheet } from "./ui/BottomSheet";

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
  const context = (
    <>
      <div className="text-xs text-tg-hint">Editing</div>
      <div className="text-sm text-tg-text font-medium truncate">{taskTitle.length > 50 ? taskTitle.substring(0, 50) + "…" : taskTitle}</div>
      <div className="flex items-center gap-1.5 mt-1">
        <span className="text-xs text-tg-subtitle">Current:</span>
        <KindBadge kind={currentKind} />
      </div>
    </>
  );

  return (
    <BottomSheet isOpen={isOpen} onClose={onClose} title="Select Type" context={context}>
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
    </BottomSheet>
  );
}
