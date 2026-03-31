import { useState, useEffect, useCallback } from "react";
import { api, UserSettings } from "../api/client";

export function useSettings() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSettings();
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const updateSetting = async (updates: Partial<UserSettings>) => {
    if (!settings) return;
    
    const previousSettings = { ...settings };
    setSettings({ ...settings, ...updates });
    
    try {
      const updated = await api.updateSettings(updates);
      setSettings(updated);
    } catch (err) {
      setSettings(previousSettings);
      throw err;
    }
  };

  return {
    settings,
    loading,
    error,
    updateSetting,
  };
}
