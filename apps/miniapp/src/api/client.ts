const API_BASE = "/api/app";

function getInitData(): string {
  return window.Telegram?.WebApp?.initData ?? "";
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {} } = options;

  const initData = getInitData();
  const fetchHeaders: Record<string, string> = {
    ...headers,
    "Content-Type": "application/json",
  };

  if (initData) {
    fetchHeaders["Authorization"] = `tma ${initData}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: fetchHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, error.detail ?? "Unknown error");
  }

  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ReviewQueueItem {
  stable_id: string;
  raw_text: string;
  normalized_title: string;
  project_name: string | null;
  kind: string;
  confidence: string;
  has_ambiguity: boolean;
  created_at: string;
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[];
  total: number;
  pending: number;
  queued: number;
}

export interface ReviewDetail {
  stable_id: string;
  raw_text: string;
  normalized_title: string;
  kind: string;
  confidence: string;
  project_name: string | null;
  project_id: string | null;
  next_action: string | null;
  due_hint: string | null;
  substeps: string[];
  ambiguities: string[];
  disambiguation_options: Record<string, unknown>[];
  telegram_message_id: number | null;
  created_at: string;
}

export interface ActionResponse {
  success: boolean;
  message: string;
}

export interface DraftResponse {
  success: boolean;
  draft_text: string | null;
  message: string;
}

export interface UserSettings {
  auto_next: boolean;
  batch_size: number;
  paused: boolean;
  sync_summary: boolean;
  daily_brief: boolean;
  show_confidence: boolean;
  show_raw_input: boolean;
  draft_suggestions: boolean;
  ambiguity_prompts: boolean;
  show_steps_auto: boolean;
  changes_only: boolean;
}

export interface ProjectListItem {
  id: string;
  name: string;
  slug: string;
  project_type: string;
  description: string | null;
  is_active: boolean;
}

export const api = {
  getQueue: (status?: string) =>
    request<ReviewQueueResponse>(`/review/queue${status ? `?status=${status}` : ""}`),

  getReview: (stableId: string) =>
    request<ReviewDetail>(`/review/${stableId}`),

  confirmReview: (stableId: string) =>
    request<ActionResponse>(`/review/${stableId}/confirm`, { method: "POST" }),

  discardReview: (stableId: string) =>
    request<ActionResponse>(`/review/${stableId}/discard`, { method: "POST" }),

  editTitle: (stableId: string, title: string) =>
    request<ActionResponse>(`/review/${stableId}/edit-title`, {
      method: "POST",
      body: { title },
    }),

  changeProject: (stableId: string, projectId: string) =>
    request<ActionResponse>(`/review/${stableId}/change-project`, {
      method: "POST",
      body: { project_id: projectId },
    }),

  changeType: (stableId: string, kind: string) =>
    request<ActionResponse>(`/review/${stableId}/change-type`, {
      method: "POST",
      body: { kind },
    }),

  clarify: (stableId: string, optionIndex: number) =>
    request<ActionResponse>(`/review/${stableId}/clarify`, {
      method: "POST",
      body: { option_index: optionIndex },
    }),

  getDraft: (stableId: string) =>
    request<DraftResponse>(`/review/${stableId}/draft`, { method: "POST" }),

  getSettings: () => request<UserSettings>("/settings"),

  updateSettings: (settings: Partial<UserSettings>) =>
    request<UserSettings>("/settings", { method: "PUT", body: settings }),

  getProjects: () => request<ProjectListItem[]>("/projects"),

  updateProjectType: (projectId: string, projectType: string) =>
    request<ActionResponse>(`/projects/${projectId}`, {
      method: "PATCH",
      body: { project_type: projectType },
    }),
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData: string;
        initDataUnsafe: Record<string, unknown>;
        ready: () => void;
        expand: () => void;
        close: () => void;
        isExpanded: boolean;
        viewportHeight: number;
        viewportStableHeight: number;
        colorScheme: "light" | "dark";
        themeParams: Record<string, string>;
        BackButton: {
          show: () => void;
          hide: () => void;
          onClick: (cb: () => void) => void;
          offClick: (cb: () => void) => void;
          isVisible: boolean;
        };
        MainButton: {
          text: string;
          color: string;
          textColor: string;
          isVisible: boolean;
          isActive: boolean;
          show: () => void;
          hide: () => void;
          enable: () => void;
          disable: () => void;
          showProgress: (leaveActive?: boolean) => void;
          hideProgress: () => void;
          onClick: (cb: () => void) => void;
          offClick: (cb: () => void) => void;
          setText: (text: string) => void;
          setParams: (params: Record<string, unknown>) => void;
        };
        HapticFeedback: {
          impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
          notificationOccurred: (type: "error" | "success" | "warning") => void;
          selectionChanged: () => void;
        };
      };
    };
  }
}
