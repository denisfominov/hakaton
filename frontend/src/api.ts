import type {
  Action,
  CompanyLookup,
  CompareRow,
  EventCard,
  EventDetail,
  Feedback,
  HistoryItem,
  Insight,
  Meta,
  ModelStatus,
  Outlet,
  Overview,
  Profile,
  ProfileOptions,
  ProfileSuggestion,
  Status,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch("/api" + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("Сервер недоступен. Проверьте, что backend запущен на порту 8000.", 0);
  }
  if (!res.ok) {
    let msg = `Ошибка ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) msg = "Проверьте заполнение полей: " + data.detail.map((d: any) => d.loc?.slice(-1)[0]).join(", ");
    } catch {
      // тело не json — оставляем стандартное сообщение
    }
    throw new ApiError(msg, res.status);
  }
  return res.json();
}

function qs(params: Record<string, string | number | boolean | undefined>) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== false) p.set(k, String(v));
  });
  return p.toString();
}

export interface EventFilters {
  q?: string;
  category?: string;
  impact?: string;
  level?: string;
  days?: number;
  mode?: string;
  favorites_only?: boolean;
  sort?: string;
  min_relevance?: number;
  min_verification?: number;
}

export const api = {
  status: () => request<Status>("/status"),
  meta: () => request<Meta>("/meta"),
  outlets: () => request<Outlet[]>("/outlets"),

  profiles: () => request<Profile[]>("/profiles"),
  createProfile: (p: Omit<Profile, "id">) => request<Profile>("/profiles", { method: "POST", body: JSON.stringify(p) }),
  updateProfile: (id: string, p: Omit<Profile, "id">) =>
    request<Profile>(`/profiles/${id}`, { method: "PUT", body: JSON.stringify(p) }),
  resetProfile: (id: string) => request<Profile>(`/profiles/${id}/reset`, { method: "POST" }),
  deleteProfile: (id: string) => request<{ ok: boolean }>(`/profiles/${id}`, { method: "DELETE" }),
  restorePresets: () => request<{ restored: string[] }>("/profiles/restore-presets", { method: "POST" }),
  lookupCompany: (b: { url: string; inn: string; name: string; industry: string; description: string }) =>
    request<CompanyLookup>("/companies/lookup", { method: "POST", body: JSON.stringify(b) }),
  profileOptions: (industry: string) => request<ProfileOptions>(`/profile-options?${qs({ industry })}`),
  suggestProfile: (b: { name: string; industry: string; description: string }) =>
    request<ProfileSuggestion>("/profiles/suggest", { method: "POST", body: JSON.stringify(b) }),

  sendFeedback: (profileId: string, id: string, f: Omit<Feedback, "updated_at">) =>
    request<{ feedback: Feedback | null; model: ModelStatus }>(`/events/${id}/feedback`, {
      method: "POST", body: JSON.stringify({ profile_id: profileId, ...f }),
    }),
  model: () => request<ModelStatus>("/model"),
  trainModel: () => request<ModelStatus>("/model/train", { method: "POST" }),
  marketRefresh: (refreshPrices: boolean) =>
    request<{ prices: { ticker: string; ok: boolean; days?: number; error?: string }[]; model: ModelStatus }>(
      `/model/market?${qs({ refresh_prices: refreshPrices })}`, { method: "POST" }),
  setModelEnabled: (enabled: boolean) =>
    request<ModelStatus>("/model/settings", { method: "PUT", body: JSON.stringify({ enabled }) }),

  overview: (profileId: string, f: { days: number; category?: string; impact?: string; level?: string }) =>
    request<Overview>(`/overview?${qs({ profile_id: profileId, ...f })}`),

  events: (profileId: string, f: EventFilters) =>
    request<{ total: number; items: EventCard[] }>(`/events?${qs({ profile_id: profileId, ...f })}`),
  event: (profileId: string, id: string) => request<EventDetail>(`/events/${id}?${qs({ profile_id: profileId })}`),
  compare: (id: string) => request<CompareRow[]>(`/events/${id}/compare`),
  toggleFavorite: (profileId: string, id: string) =>
    request<{ favorite: boolean }>(`/events/${id}/favorite?${qs({ profile_id: profileId })}`, { method: "POST" }),
  runLlm: (profileId: string, id: string) =>
    request<{ insight: Insight }>(`/events/${id}/llm?${qs({ profile_id: profileId })}`, { method: "POST" }),

  refresh: (mode: "dataset" | "live") =>
    request<{ mode: string; report: { source: string; ok: boolean; added?: number; error?: string; skipped?: boolean;
      country?: string }[]; message?: string | null }>(
      "/refresh",
      { method: "POST", body: JSON.stringify({ mode }) },
    ),

  actions: (profileId: string) => request<Action[]>(`/actions?${qs({ profile_id: profileId })}`),
  createAction: (a: Partial<Action> & { profile_id: string; title: string }) =>
    request<Action>("/actions", { method: "POST", body: JSON.stringify(a) }),
  updateAction: (id: number, patch: Partial<Action>) =>
    request<Action>(`/actions/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  actionHistory: (id: number) => request<HistoryItem[]>(`/actions/${id}/history`),
};
