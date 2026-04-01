import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { mainButton, hapticFeedback } from "@telegram-apps/sdk-react";
import { Layout } from "../components/Layout";
import { FieldEditor } from "../components/FieldEditor";
import { ProjectPicker } from "../components/ProjectPicker";
import { KindPicker } from "../components/KindPicker";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { KindBadge } from "../components/KindBadge";
import { AmbiguityPicker } from "../components/AmbiguityPicker";
import { ScreenContent, Card } from "../components/ui";
import { useReview } from "../hooks/useReview";
import { useQueue } from "../hooks/useQueue";

export function ReviewScreen() {
  const { stableId } = useParams<{ stableId: string }>();
  const navigate = useNavigate();
  const { 
    review, loading, error, 
    confirm, discard, editTitle, changeProject, changeType, clarify, getDraft 
  } = useReview(stableId);
  const { items, counts } = useQueue();

  const [isProjectPickerOpen, setIsProjectPickerOpen] = useState(false);
  const [isKindPickerOpen, setIsKindPickerOpen] = useState(false);
  const [isAmbiguityPickerOpen, setIsAmbiguityPickerOpen] = useState(false);
  const [draftText, setDraftText] = useState<string | null>(null);
  const [isDraftLoading, setIsDraftLoading] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [clarifyingIdx, setClarifyingIdx] = useState<number | null>(null);

  const currentIndex = items.findIndex(item => item.stable_id === stableId);
  const positionText = currentIndex >= 0 ? `${currentIndex + 1} of ${counts.total}` : "";

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

  const handleClarify = async (idx: number) => {
    setClarifyingIdx(idx);
    try {
      await clarify(idx);
      setIsAmbiguityPickerOpen(false);
    } finally {
      setClarifyingIdx(null);
    }
  };

  if (loading) {
    return (
      <Layout title="Review">
        <ScreenContent>
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-4 border-tg-secondary-bg border-t-tg-button rounded-full animate-spin"></div>
          </div>
        </ScreenContent>
      </Layout>
    );
  }

  if (error || !review) {
    return (
      <Layout title="Review">
        <ScreenContent>
          <div className="text-center">
            <div className="text-red-500 mb-2">Failed to load review</div>
            <div className="text-tg-hint text-sm">{error}</div>
          </div>
        </ScreenContent>
      </Layout>
    );
  }

  return (
    <Layout 
      title="Review"
      rightAction={
        positionText ? (
          <div className="text-xs text-tg-hint bg-tg-secondary-bg px-2 py-0.5 rounded-full">
            {positionText}
          </div>
        ) : undefined
      }
    >
      <ScreenContent bottomPadding="pb-28">
        <div className="mb-4">
          <button 
            onClick={() => setShowRaw(!showRaw)}
            className="w-full bg-tg-section-bg rounded-2xl p-3 active:bg-tg-secondary-bg transition-colors text-left"
          >
            <div className="flex justify-between items-center mb-1">
              <div className="text-xs font-medium text-tg-hint uppercase tracking-wide">What you said</div>
              <svg className={`w-4 h-4 text-tg-hint transition-transform ${showRaw ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
            {showRaw ? (
              <div className="bg-tg-secondary-bg rounded-2xl p-3 font-mono text-xs text-tg-text whitespace-pre-wrap mt-2">
                {review.raw_text}
              </div>
            ) : (
              <div className="text-sm text-tg-text truncate">
                {review.raw_text.length > 80 ? review.raw_text.substring(0, 80) + "..." : review.raw_text}
              </div>
            )}
          </button>
        </div>

        {review.ambiguities && review.ambiguities.length > 0 && (
          <div className="mb-4">
            <button
              onClick={() => setIsAmbiguityPickerOpen(true)}
              className="w-full flex items-center gap-3 bg-amber-500/10 p-3 rounded-2xl active:bg-amber-500/20 transition-colors text-left"
            >
              <svg className="w-5 h-5 text-amber-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-amber-600 dark:text-amber-400">Needs Clarification</div>
                <div className="text-xs text-tg-hint mt-0.5 truncate">
                  {review.ambiguities.length} issue{review.ambiguities.length > 1 ? "s" : ""} — tap to resolve
                </div>
              </div>
              <svg className="w-5 h-5 text-tg-hint shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        )}

        <div className="space-y-4 mb-6">
          <FieldEditor 
            label="Title" 
            value={review.normalized_title} 
            onSave={editTitle} 
          />

          <div className="flex items-center gap-2">
            <button onClick={() => setIsKindPickerOpen(true)} className="active:opacity-70 transition-opacity">
              <KindBadge kind={review.kind} />
            </button>
            <ConfidenceBadge confidence={review.confidence} />
          </div>

          <Card interactive onClick={() => setIsProjectPickerOpen(true)} className="!p-3 flex justify-between items-center">
            <div>
              <div className="text-xs text-tg-hint mb-0.5">Project</div>
              <div className="text-tg-text font-medium">{review.project_name || "Inbox"}</div>
            </div>
            <svg className="w-5 h-5 text-tg-hint" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Card>

          {review.next_action && (
            <Card className="!p-3">
              <div className="text-xs text-tg-hint mb-1">Next Action</div>
              <div className="text-tg-text text-sm">{review.next_action}</div>
            </Card>
          )}

          {review.due_hint && (
            <Card className="!p-3">
              <div className="text-xs text-tg-hint mb-1">Due Hint</div>
              <div className="text-tg-text text-sm">{review.due_hint}</div>
            </Card>
          )}

          {review.substeps && review.substeps.length > 0 && (
            <div>
              <h3 className="text-xs font-medium text-tg-hint uppercase tracking-wide mb-2">Substeps</h3>
              <div className="bg-tg-section-bg rounded-2xl overflow-hidden">
                {review.substeps.map((step, idx) => (
                  <div key={idx} className="p-3 border-b border-tg-secondary-bg last:border-b-0 flex gap-3">
                    <div className="text-tg-hint text-sm mt-0.5">{idx + 1}.</div>
                    <div className="text-tg-text text-sm">{step}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-3">
          <button 
            onClick={handleLoadDraft}
            disabled={isDraftLoading}
            className="w-full py-3 rounded-2xl bg-tg-section-bg text-tg-link font-medium active:opacity-70 flex justify-center items-center"
          >
            {isDraftLoading ? (
              <div className="w-5 h-5 border-2 border-tg-link border-t-transparent rounded-full animate-spin"></div>
            ) : (
              "Draft Message"
            )}
          </button>
          
          {draftText && (
            <Card className="!p-3 text-sm text-tg-text whitespace-pre-wrap border border-tg-link/30">
              {draftText}
            </Card>
          )}

          <button 
            onClick={handleDiscard}
            className="w-full py-3 rounded-2xl bg-tg-destructive/10 text-tg-destructive font-medium active:opacity-70"
          >
            Discard
          </button>
        </div>
      </ScreenContent>

      <ProjectPicker 
        isOpen={isProjectPickerOpen} 
        onClose={() => setIsProjectPickerOpen(false)} 
        onSelect={changeProject}
        currentProjectId={review.project_id}
        taskTitle={review.normalized_title}
        currentProjectName={review.project_name}
      />
      
      <KindPicker 
        isOpen={isKindPickerOpen} 
        onClose={() => setIsKindPickerOpen(false)} 
        onSelect={changeType}
        currentKind={review.kind}
        taskTitle={review.normalized_title}
      />

      <AmbiguityPicker
        isOpen={isAmbiguityPickerOpen}
        onClose={() => setIsAmbiguityPickerOpen(false)}
        onSelect={handleClarify}
        ambiguities={review.ambiguities}
        options={review.disambiguation_options}
        taskTitle={review.normalized_title}
        clarifyingIdx={clarifyingIdx}
      />
    </Layout>
  );
}
