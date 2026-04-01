import { ProjectTypeBadge } from "./ProjectTypeBadge";
import { BottomSheet } from "./ui/BottomSheet";

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
  const context = (
    <>
      <div className="text-xs text-tg-hint">Changing category for</div>
      <div className="text-sm text-tg-text font-medium truncate">{projectName}</div>
    </>
  );

  return (
    <BottomSheet isOpen={isOpen} onClose={onClose} title="Select Category" context={context}>
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
    </BottomSheet>
  );
}
