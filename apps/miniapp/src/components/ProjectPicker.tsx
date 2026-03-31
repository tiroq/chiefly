import { useState, useEffect } from "react";
import { api, ProjectListItem } from "../api/client";

interface ProjectPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (projectId: string) => void;
  currentProjectId: string | null;
}

export function ProjectPicker({ isOpen, onClose, onSelect, currentProjectId }: ProjectPickerProps) {
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
      <div className="w-full bg-tg-bg rounded-t-2xl max-h-[80vh] flex flex-col">
        <div className="flex justify-between items-center p-4 border-b border-tg-secondary-bg">
          <h2 className="text-lg font-semibold text-tg-text">Select Project</h2>
          <button onClick={onClose} className="text-tg-link font-medium">
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
                  className={`flex items-center justify-between p-3 rounded-xl text-left transition-colors ${
                    currentProjectId === project.id ? "bg-tg-secondary-bg" : "active:bg-tg-secondary-bg"
                  }`}
                >
                  <div>
                    <div className="font-medium text-tg-text">{project.name}</div>
                    {project.description && (
                      <div className="text-xs text-tg-subtitle mt-0.5">{project.description}</div>
                    )}
                  </div>
                  <span className="text-[10px] px-2 py-1 rounded-full bg-tg-section-bg text-tg-hint border border-tg-secondary-bg">
                    {project.project_type}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
