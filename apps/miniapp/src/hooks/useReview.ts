import { useState, useEffect, useCallback } from "react";
import { api, ReviewDetail } from "../api/client";

export function useReview(stableId: string | undefined) {
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReview = useCallback(async () => {
    if (!stableId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getReview(stableId);
      setReview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch review");
    } finally {
      setLoading(false);
    }
  }, [stableId]);

  useEffect(() => {
    fetchReview();
  }, [fetchReview]);

  const confirm = async () => {
    if (!stableId) return;
    await api.confirmReview(stableId);
  };

  const discard = async () => {
    if (!stableId) return;
    await api.discardReview(stableId);
  };

  const editTitle = async (title: string) => {
    if (!stableId) return;
    await api.editTitle(stableId, title);
    await fetchReview();
  };

  const changeProject = async (projectId: string) => {
    if (!stableId) return;
    await api.changeProject(stableId, projectId);
    await fetchReview();
  };

  const changeType = async (kind: string) => {
    if (!stableId) return;
    await api.changeType(stableId, kind);
    await fetchReview();
  };

  const clarify = async (optionIndex: number) => {
    if (!stableId) return;
    await api.clarify(stableId, optionIndex);
    await fetchReview();
  };

  const getDraft = async () => {
    if (!stableId) return null;
    return await api.getDraft(stableId);
  };

  return {
    review,
    loading,
    error,
    confirm,
    discard,
    editTitle,
    changeProject,
    changeType,
    clarify,
    getDraft,
    refresh: fetchReview,
  };
}
