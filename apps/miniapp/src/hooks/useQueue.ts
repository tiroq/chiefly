import { useState, useEffect, useCallback } from "react";
import { api, ReviewQueueItem } from "../api/client";

export type QueueFilter = "pending" | "queued" | "ambiguous" | null;

export function useQueue() {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [counts, setCounts] = useState({ total: 0, pending: 0, queued: 0 });
  const [filter, setFilter] = useState<QueueFilter>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.getQueue(filter || undefined);
      setItems(response.items);
      setCounts({
        total: response.total,
        pending: response.pending,
        queued: response.queued,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch queue");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  return {
    items,
    counts,
    filter,
    setFilter,
    loading,
    error,
    refresh: fetchQueue,
  };
}
