export type Health = {
  status: string;
  companies: number;
  links: number;
  payments: number;
};

export type CompanySummary = {
  SYNTHETIC_U: string;
  GROUP_ID: string | null;
  CL_TYPE: string;
  MAINOKVED_CODE: string | null;
  MAINOKVED_NAME: string | null;
  REGION: string | null;
  REVENUE_COMPANY: number | null;
  GROUP_REVENUE: number | null;
  IS_LARGE: boolean;
};

export type CompanyPage = { total: number; items: CompanySummary[] };

export type Reference = {
  regions: { name: string; companies: number }[];
  industries: { industry: string; name: string }[];
};

export type Provenance = "fact" | "bank" | "model" | "hypothesis";

export type SourceRef = { kind: string; ref: string; quote: string | null; url: string | null };

export type Feature = { name: string; value: string | number | boolean | null; source: SourceRef; confidence: number };

export type Claim = { text: string; provenance: Provenance; sources: SourceRef[]; confidence: number | null };

export type Sensitivity = {
  factor: string;
  weight: number;
  provenance: Provenance;
  scope: string;
  reasons: string[];
  sources: SourceRef[];
};

export type IndustryShare = { industry: string; label: string | null; share: number };

export type Position = { scope: string; key: string; rank: number | null; peers: number; revenue_share_in_sample: number | null };

export type GroupMember = {
  uid: string;
  okved_code: string | null;
  okved_name: string | null;
  region: string | null;
  revenue: number | null;
  revenue_share: number | null;
  is_client: boolean;
  role: string;
  role_basis: string;
};

export type GroupInfo = {
  group_id: string;
  size: number;
  revenue: number | null;
  is_large: boolean;
  clients: number;
  industries: IndustryShare[];
  regions: string[];
  members: GroupMember[];
};

export type CompanyProfile = {
  uid: string;
  group_id: string | null;
  client_type: string | null;
  okved_code: string | null;
  okved_name: string | null;
  industry: string | null;
  industry_label: string | null;
  region: string | null;
  city: string | null;
  revenue: number | null;
  group_revenue: number | null;
  is_large: boolean;
  products: string[];
  trade_countries: string[];
  features: Feature[];
  group: GroupInfo | null;
  positions: Position[];
  hypotheses: Claim[];
  sensitivities: Sensitivity[];
  data_gaps: string[];
};

export type CompanyFilter = {
  large: boolean;
  region: string;
  okved: string;
  limit: number;
  offset: number;
};

export type SourceView = { kind: string; ref: string; title: string | null; url: string | null; quote: string | null };

export type ClaimView = { text: string; provenance: Provenance; confidence: number | null; sources: SourceView[] };

export type NewsLink = { source: string; title: string; url: string | null; published_at: string | null };

export type Impact = "low" | "medium" | "high";

export type InsightCard = {
  id: string;
  company_uid: string;
  news_id: string;
  created_at: string;
  relevance: number;
  impact: Impact;
  impact_reason: string | null;
  title: string;
  headline: string | null;
  published_at: string | null;
  news: NewsLink[];
  event_summary: string | null;
  sections: Record<string, ClaimView[]>;
  provenance_counts: Record<string, number>;
  has_bank_view: boolean;
  matched_factors: string[];
  role: string | null;
  role_focus: string[];
  sections_order: string[];
  trace_id: string | null;
  feedback: Record<string, number>;
};

export type TraceStep = { kind: string; name: string; ms: number | null; error: string | null };

export type LlmCall = {
  role: string;
  model: string;
  purpose: string | null;
  ms: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  ok: boolean;
};

export type Trace = { id: string; status: string; steps: TraceStep[]; llm_calls: LlmCall[] };

export type Job = {
  id: string;
  company_uid: string;
  status: "queued" | "running" | "done" | "failed";
  results: { status: string; insight_id: string | null }[];
  error: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body && typeof body.detail === "string" ? `: ${body.detail}` : "";
    throw new Error(`${response.status} ${response.statusText}${detail}`);
  }
  return response.json() as Promise<T>;
}

export const getJson = <T>(path: string) => request<T>(path);

export const getHealth = () => getJson<Health>("/health");

export const getReference = () => getJson<Reference>("/reference");

export const getProfile = (companyId: string) => getJson<CompanyProfile>(`/companies/${encodeURIComponent(companyId)}/profile`);

export function getCompanies(filter: CompanyFilter) {
  const query = new URLSearchParams({ limit: String(filter.limit), offset: String(filter.offset) });
  if (filter.large) query.set("large", "true");
  if (filter.region) query.set("region", filter.region);
  if (filter.okved.trim()) query.set("okved", filter.okved.trim());
  return getJson<CompanyPage>(`/companies?${query}`);
}

export const getCards = (companyId: string, role: string) =>
  getJson<InsightCard[]>(`/companies/${encodeURIComponent(companyId)}/cards?role=${role}&limit=20`);

export const startAnalysis = (companyId: string) =>
  request<Job>(`/companies/${encodeURIComponent(companyId)}/analyze?limit=3&days=3`, { method: "POST" });

export const getJob = (jobId: string) => getJson<Job>(`/jobs/${jobId}`);

export const getCard = (insightId: string, role: string) =>
  getJson<InsightCard>(`/insights/${encodeURIComponent(insightId)}/card?role=${role}`);

export const getTrace = (insightId: string) => getJson<Trace>(`/insights/${encodeURIComponent(insightId)}/trace`);

export type InsightAnswer = {
  id: string;
  question: string;
  answer: string;
  answerable: boolean;
  claims: ClaimView[];
  follow_up: string[];
};

export type FeedbackKind = "useful" | "not_useful" | "hide" | "unhide" | "open_source";

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getQuestions = (insightId: string) =>
  getJson<InsightAnswer[]>(`/insights/${encodeURIComponent(insightId)}/questions`);

export const askQuestion = (insightId: string, question: string, role: string) =>
  request<InsightAnswer>(`/insights/${encodeURIComponent(insightId)}/ask`, json({ question, role }));

export const sendFeedback = (insightId: string, kind: FeedbackKind, role: string, sourceUrl?: string) =>
  request<{ id: string; counts: Record<string, number> }>(`/insights/${encodeURIComponent(insightId)}/feedback`,
    json({ kind, role, source_url: sourceUrl ?? null }));
