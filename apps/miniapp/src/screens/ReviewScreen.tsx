import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { mainButton, hapticFeedback } from "@telegram-apps/sdk-react";
import { Layout } from "../components/Layout";
import { FieldEditor } from "../components/FieldEditor";
import { ProjectPicker } from "../components/ProjectPicker";
import { KindPicker } from "../components/KindPicker";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { KindBadge } from "../components/KindBadge";
import { useReview } from "../hooks/useReview";

export function ReviewScreen() {
  const { stableId } = useParams<{ stableId: string }>();
  const navigate = useNavigate();
  const { 
    review, loading, error, 
    confirm, discard, editTitle, changeProject, changeType, clarify, getDraft 
  } = useReview(stableId);

  const [isProjectPickerOpen, setIsProjectPickerOpen] = useState(false);
  const [isKindPickerOpen, setIsKindPickerOpen] = useState(false);
  const [draftText, setDraftText] = useState<string | null>(null);
  const [isDraftLoading, setIsDraftLoading] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (review) {
      mainButton.setParams({
        text: "Confirm",
        isVisible: true,
        isEnabled: true,
      });
      
      const handleConfirm = async () => {
        try {
          mainButton.setParams({ isLoaderVisible: true });
          await confirm();
          hapticFeedback.notificationOccurred("success");
          navigate(-1);
        } catch (err) {
          hapticFeedback.notificationOccurred("error");
          console.error(err);
        } finally {
          mainButton.setParams({ isLoaderVisible: false });
        }
      };
      
      const unsub = mainButton.onClick(handleConfirm);
      
      return () => {
        unsub();
        mainButton.setParams({ isVisible: false });
      };
    } else {
      mainButton.setParams({ isVisible: false });
    }
  }, [review, confirm, navigate]);

  const handleDiscard = async () => {
    if (window.confirm("Are you sure you want to discard this item?")) {
      try {
        await discard();
        hapticFeedback.impactOccurred("medium");
        navigate(-1);
      } catch (err) {
        console.error(err);
      }
    }
  };

  const handleLoadDraft = async () => {
    setIsDraftLoading(true);
    try {
      const res = await getDraft();
      if (res?.draft_text) {
        setDraftText(res.draft_text);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsDraftLoading(false);
    }
  };

  if (loading) {
    return (
      <Layout title="Review">
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-4 border-tg-secondary-bg border-t-tg-button rounded-full animate-spin"></div>
        </div>
      </Layout>
    );
  }

  if (error || !review) {
    return (
      <Layout title="Review">
        <div className="p-4 text-center">
          <div className="text-red-500 mb-2">Failed to load review</div>
          <div className="text-tg-hint text-sm">{error}</div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Review">
      <div className="p-4 pb-24">
        <div className="flex gap-2 mb-4">
          <button onClick={() => setIsKindPickerOpen(true)}>
            <KindBadge kind={review.kind} />
          </button>
          <ConfidenceBadge confidence={review.confidence} />
        </div>

        <div className="mb-6">
          <FieldEditor 
            label="Title" 
            value={review.normalized_title} 
            onSave={editTitle} 
          />
        </div>

        <div className="space-y-3 mb-6">
          <button 
            onClick={() => setIsProjectPickerOpen(true)}
            className="w-full flex justify-between items-center bg-tg-section-bg p-3 rounded-xl active:bg-tg-secondary-bg transition-colors text-left"
          >
            <div>
              <div className="text-xs text-tg-hint mb-0.5">Project</div>
              <div className="text-tg-text font-medium">{review.project_name || "Inbox"}</div>
            </div>
            <svg className="w-5 h-5 text-tg-hint" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>

          {review.next_action && (
            <div className="bg-tg-section-bg p-3 rounded-xl">
              <div className="text-xs text-tg-hint mb-1">Next Action</div>
              <div className="text-tg-text text-sm">{review.next_action}</div>
            </div>
          )}

          {review.due_hint && (
            <div className="bg-tg-section-bg p-3 rounded-xl">
              <div className="text-xs text-tg-hint mb-1">Due Hint</div>
              <div className="text-tg-text text-sm">{review.due_hint}</div>
            </div>
          )}
        </div>

        {review.substeps && review.substeps.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-tg-section-header mb-2 uppercase tracking-wider">Substeps</h3>
            <div className="bg-tg-section-bg rounded-xl overflow-hidden">
              {review.substeps.map((step, idx) => (
                <div key={idx} className="p-3 border-b border-tg-secondary-bg last:border-b-0 flex gap-3">
                  <div className="text-tg-hint text-sm mt-0.5">{idx + 1}.</div>
                  <div className="text-tg-text text-sm">{step}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {review.ambiguities && review.ambiguities.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-red-500 mb-2 uppercase tracking-wider">Ambiguities</h3>
            <div className="bg-red-50 dark:bg-red-900/10 rounded-xl p-3 border border-red-100 dark:border-red-900/30">
              <ul className="list-disc pl-4 space-y-1">
                {review.ambiguities.map((amb, idx) => (
                  <li key={idx} className="text-sm text-red-800 dark:text-red-400">{amb}</li>
                ))}
              </ul>
              
              {review.disambiguation_options && review.disambiguation_options.length > 0 && (
                <div className="mt-4 space-y-2">
                  {review.disambiguation_options.map((opt: Record<string, unknown>, idx) => (
                    <button
                      key={idx}
                      onClick={() => clarify(idx)}
                      className="w-full text-left p-2 rounded-lg bg-white dark:bg-black/20 border border-red-200 dark:border-red-900/50 text-sm active:opacity-70"
                    >
                      <div className="font-medium text-tg-text">{String(opt.title || `Option ${idx + 1}`)}</div>
                      {!!opt.description && <div className="text-xs text-tg-hint mt-0.5">{String(opt.description)}</div>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="mb-6">
          <button 
            onClick={() => setShowRaw(!showRaw)}
            className="flex items-center text-sm text-tg-link font-medium mb-2"
          >
            {showRaw ? "Hide Raw Input" : "Show Raw Input"}
            <svg className={`w-4 h-4 ml-1 transition-transform ${showRaw ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          
          {showRaw && (
            <div className="bg-tg-secondary-bg p-3 rounded-xl text-sm text-tg-text whitespace-pre-wrap font-mono text-xs">
              {review.raw_text}
            </div>
          )}
        </div>

        <div className="space-y-3">
          <button 
            onClick={handleLoadDraft}
            disabled={isDraftLoading}
            className="w-full py-3 rounded-xl bg-tg-section-bg text-tg-link font-medium active:opacity-70 flex justify-center items-center"
          >
            {isDraftLoading ? (
              <div className="w-5 h-5 border-2 border-tg-link border-t-transparent rounded-full animate-spin"></div>
            ) : (
              "Draft Message"
            )}
          </button>
          
          {draftText && (
            <div className="bg-tg-section-bg p-3 rounded-xl text-sm text-tg-text whitespace-pre-wrap border border-tg-link/30">
              {draftText}
            </div>
          )}

          <button 
            onClick={handleDiscard}
            className="w-full py-3 rounded-xl bg-red-100 text-red-600 dark:bg-red-900/20 dark:text-red-500 font-medium active:opacity-70"
          >
            Discard
          </button>
        </div>
      </div>

      <ProjectPicker 
        isOpen={isProjectPickerOpen} 
        onClose={() => setIsProjectPickerOpen(false)} 
        onSelect={changeProject}
        currentProjectId={review.project_id}
      />
      
      <KindPicker 
        isOpen={isKindPickerOpen} 
        onClose={() => setIsKindPickerOpen(false)} 
        onSelect={changeType}
        currentKind={review.kind}
      />
    </Layout>
  );
}
