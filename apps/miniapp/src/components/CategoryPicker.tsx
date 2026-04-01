import { ProjectTypeBadge } from "./ProjectTypeBadge";

const PROJECT_TYPES = [
  { value: "personal", description: "Personal tasks and goals" },
  { value: "family", description: "Family-related tasks" },
  { value: "client", description: "Client work and deliverables" },
  { value: "ops", description: "Operations and admin" },
  { value: "writing", description: "Writing and content" },
  { value: "internal", description: "Internal projects" },
];

interface CategoryPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (projectType: string) => void;
  currentType: string;
  projectName: string;
}

export function CategoryPicker({ isOpen, onClose, onSelect, currentType, projectName }: CategoryPickerProps) {
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
        <div className="w-10 h-1 bg-tg-hint/30 rounded-full mx-auto mt-3 mb-1" />

        <div className="px-4 pt-1 pb-2">
          <div className="text-xs text-tg-hint">Changing category for</div>
          <div className="text-sm text-tg-text font-medium truncate">
            {projectName}
          </div>
        </div>

        <div className="flex justify-between items-center px-4 pb-3 border-b border-tg-secondary-bg">
          <h2 className="text-lg font-semibold text-tg-text">Select Category</h2>
          <button
            onClick={onClose}
            className="text-sm font-medium text-tg-hint active:text-tg-text transition-colors"
          >
            Cancel
          </button>
        </div>

        <div className="overflow-y-auto p-2">
          <div className="flex flex-col gap-1">
            {PROJECT_TYPES.map((type) => {
              const isSelected = currentType.toLowerCase() === type.value;
              return (
                <button
                  key={type.value}
                  onClick={() => {
                    onSelect(type.value);
                    onClose();
                  }}
                  className={`flex items-center justify-between p-3.5 rounded-xl text-left transition-colors ${
                    isSelected ? "bg-tg-secondary-bg" : "active:bg-tg-secondary-bg"
                  }`}
                >
                  <div>
                    <div className="mb-1">
                      <ProjectTypeBadge projectType={type.value} />
                    </div>
                    <div className="text-xs text-tg-subtitle">{type.description}</div>
                  </div>
                  {isSelected && (
                    <svg className="w-5 h-5 text-tg-link shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
