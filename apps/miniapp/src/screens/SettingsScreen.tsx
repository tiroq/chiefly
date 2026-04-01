import { Layout } from "../components/Layout";
import { ToggleSetting } from "../components/ToggleSetting";
import { useSettings } from "../hooks/useSettings";

export function SettingsScreen() {
  const { settings, loading, error, updateSetting } = useSettings();

  if (loading) {
    return (
      <Layout title="Settings">
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-4 border-tg-secondary-bg border-t-tg-button rounded-full animate-spin"></div>
        </div>
      </Layout>
    );
  }

  if (error || !settings) {
    return (
      <Layout title="Settings">
        <div className="p-4 text-center">
          <div className="text-red-500 mb-2">Failed to load settings</div>
          <div className="text-tg-hint text-sm">{error}</div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Settings">
      <div className="px-4 pt-4 pb-4">
        <div className="mb-6">
          <h2 className="text-xs font-medium text-tg-hint uppercase tracking-wide mb-2">Queue</h2>
          <div className="bg-tg-section-bg rounded-2xl overflow-hidden">
            <ToggleSetting
              label="Auto-advance"
              description="Move to next task after confirm/discard"
              checked={settings.auto_next}
              onChange={(checked) => updateSetting({ auto_next: checked })}
            />
            <ToggleSetting
              label="Pause queue"
              description="Stop sending new proposals"
              checked={settings.paused}
              onChange={(checked) => updateSetting({ paused: checked })}
            />
            
            <div className="flex items-center justify-between py-3 px-4 bg-tg-section-bg border-t border-tg-secondary-bg">
              <div className="flex-1 pr-4">
                <div className="text-sm font-medium text-tg-text">Batch size</div>
                <div className="text-xs text-tg-hint">Tasks sent at once</div>
              </div>
              <div className="flex bg-tg-secondary-bg rounded-lg p-1">
                {[1, 5, 10].map((size) => (
                  <button
                    key={size}
                    onClick={() => updateSetting({ batch_size: size })}
                    className={`min-w-[40px] px-3 py-1 text-sm font-medium rounded-md transition-colors ${
                      settings.batch_size === size 
                        ? "bg-tg-button text-tg-button-text shadow-sm" 
                        : "text-tg-hint active:bg-tg-hint/20"
                    }`}
                  >
                    {size}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="mb-6">
          <h2 className="text-xs font-medium text-tg-hint uppercase tracking-wide mb-2">Display</h2>
          <div className="bg-tg-section-bg rounded-2xl overflow-hidden">
            <ToggleSetting
              label="Show confidence"
              description="Display AI confidence level"
              checked={settings.show_confidence}
              onChange={(checked) => updateSetting({ show_confidence: checked })}
            />
            <ToggleSetting
              label="Show raw input"
              description="Display original text"
              checked={settings.show_raw_input}
              onChange={(checked) => updateSetting({ show_raw_input: checked })}
            />
            <ToggleSetting
              label="Auto-show steps"
              description="Expand substeps automatically"
              checked={settings.show_steps_auto}
              onChange={(checked) => updateSetting({ show_steps_auto: checked })}
            />
            <ToggleSetting
              label="Changes only"
              description="Only show items with changes"
              checked={settings.changes_only}
              onChange={(checked) => updateSetting({ changes_only: checked })}
            />
          </div>
        </div>

        <div className="mb-8">
          <h2 className="text-xs font-medium text-tg-hint uppercase tracking-wide mb-2">Features</h2>
          <div className="bg-tg-section-bg rounded-2xl overflow-hidden">
            <ToggleSetting
              label="Draft suggestions"
              description="Auto-generate draft messages"
              checked={settings.draft_suggestions}
              onChange={(checked) => updateSetting({ draft_suggestions: checked })}
            />
            <ToggleSetting
              label="Ambiguity prompts"
              description="Ask when task is unclear"
              checked={settings.ambiguity_prompts}
              onChange={(checked) => updateSetting({ ambiguity_prompts: checked })}
            />
            <ToggleSetting
              label="Sync summaries"
              description="Show sync results"
              checked={settings.sync_summary}
              onChange={(checked) => updateSetting({ sync_summary: checked })}
            />
            <ToggleSetting
              label="Daily brief"
              description="Receive daily review"
              checked={settings.daily_brief}
              onChange={(checked) => updateSetting({ daily_brief: checked })}
            />
          </div>
        </div>
      </div>
    </Layout>
  );
}
