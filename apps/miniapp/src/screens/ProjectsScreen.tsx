import { useState, useEffect, useCallback } from "react";
import { Layout } from "../components/Layout";
import { ProjectTypeBadge } from "../components/ProjectTypeBadge";
import { CategoryPicker } from "../components/CategoryPicker";
import { ScreenContent, Card, EmptyState } from "../components/ui";
import { api, ProjectListItem } from "../api/client";

export function ProjectsScreen() {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pickerProject, setPickerProject] = useState<ProjectListItem | null>(null);

  useEffect(() => {
    api.getProjects()
      .then(setProjects)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load projects"))
      .finally(() => setLoading(false));
  }, []);

  const handleCategoryChange = useCallback(async (projectId: string, newType: string) => {
    try {
      await api.updateProjectType(projectId, newType);
      setProjects((prev) =>
        prev.map((p) =>
          p.id === projectId ? { ...p, project_type: newType } : p
        )
      );
    } catch (err) {
      console.error("Failed to update project type:", err);
    }
  }, []);

  if (loading) {
    return (
      <Layout title="Projects">
        <ScreenContent>
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-4 border-tg-secondary-bg border-t-tg-button rounded-full animate-spin"></div>
          </div>
        </ScreenContent>
      </Layout>
    );
  }

  if (error) {
    return (
      <Layout title="Projects">
        <ScreenContent>
          <div className="text-center">
            <div className="text-red-500 mb-2">Failed to load projects</div>
            <div className="text-tg-hint text-sm">{error}</div>
          </div>
        </ScreenContent>
      </Layout>
    );
  }

  return (
    <Layout title="Projects">
      <ScreenContent>
        <div className="flex flex-col gap-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              className={!project.is_active ? "opacity-60" : ""}
            >
              <div className="flex justify-between items-center mb-1">
                <h3 className="text-tg-text font-semibold text-base">{project.name}</h3>
                <ProjectTypeBadge
                  projectType={project.project_type}
                  interactive={project.is_active}
                  onClick={() => setPickerProject(project)}
                />
              </div>
              
              {project.description && (
                <p className="text-tg-subtitle text-sm mt-1">
                  {project.description}
                </p>
              )}
              
              {!project.is_active && (
                <div className="mt-2 text-xs text-red-500 font-medium">
                  Inactive
                </div>
              )}
            </Card>
          ))}
          
          {projects.length === 0 && (
            <EmptyState
              title="No projects configured"
              subtitle="Projects will appear here once added."
            />
          )}
        </div>
      </ScreenContent>

      {pickerProject && (
        <CategoryPicker
          isOpen={true}
          onClose={() => setPickerProject(null)}
          onSelect={(type) => handleCategoryChange(pickerProject.id, type)}
          currentType={pickerProject.project_type}
          projectName={pickerProject.name}
        />
      )}
    </Layout>
  );
}
