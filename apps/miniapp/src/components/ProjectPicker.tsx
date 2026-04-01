import { useState, useEffect } from "react";
import { api, ProjectListItem } from "../api/client";

interface ProjectPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (projectId: string) => void;
  currentProjectId: string | null;
  taskTitle: string;
  currentProjectName: string | null;
}

export function ProjectPicker({ isOpen, onClose, onSelect, currentProjectId, taskTitle, currentProjectName }: ProjectPickerProps) {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && projects.length === 0) {
      setLoading(true);
      api.getProjects()
        .then(setProjects)
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [isOpen, projects.length]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/50 transition-opacity">
      <div className="w-full bg-tg-section-bg rounded-t-2xl max-h-[80vh] flex flex-col pb-safe">
        <div className="w-10 h-1 bg-tg-hint/30 rounded-full mx-auto mt-3 mb-1" />
        
        <div className="px-4 pt-1 pb-2">
          <div className="text-xs text-tg-hint">Editing</div>
          <div className="text-sm text-tg-text font-medium truncate">{taskTitle.length > 50 ? taskTitle.substring(0, 50) + "…" : taskTitle}</div>
          <div className="text-xs text-tg-subtitle mt-1">Current: {currentProjectName || "Inbox"}</div>
        </div>

        <div className="flex justify-between items-center p-4 border-b border-tg-secondary-bg">
          <h2 className="text-lg font-semibold text-tg-text">Select Project</h2>
          <button onClick={onClose} className="text-sm font-medium text-tg-hint active:text-tg-text transition-colors">
            Cancel
          </button>
        </div>
        
        <div className="overflow-y-auto p-2">
          {loading ? (
            <div className="p-4 text-center text-tg-hint">Loading projects...</div>
          ) : (
            <div className="flex flex-col gap-1">
              {projects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => {
                    onSelect(project.id);
                    onClose();
                  }}
                  className={`flex items-center justify-between p-3.5 rounded-xl text-left transition-colors ${
                    currentProjectId === project.id ? "bg-tg-secondary-bg" : "active:bg-tg-secondary-bg"
                  }`}
                >
                  <div>
                    <div className="font-medium text-tg-text">{project.name}</div>
                    {project.description && (
                      <div className="text-xs text-tg-subtitle mt-0.5">{project.description}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] px-2 py-1 rounded-full bg-tg-bg text-tg-hint border border-tg-secondary-bg">
                      {project.project_type}
                    </span>
                    {currentProjectId === project.id && (
                      <svg className="w-5 h-5 text-tg-link" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
