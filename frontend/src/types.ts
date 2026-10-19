export type Level = "critical" | "high" | "medium" | "low";
export type ImpactType = "risk" | "opportunity" | "neutral" | "mixed";

export interface Profile {
  id: string;
  name: string;
  aliases: string[];
  kind?: string;
  source_note?: string;
  description: string;
  industry: string;
  subindustries: string[];
  regions: string[];
  products: string[];
  clients: string[];
  suppliers: string[];
  competitors: string[];
  goals: string[];
  priorities: string[];
  risks: string[];
  investment_plans: string[];
  keywords: string[];
  // тикер на Мосбирже: новости публичной компании размечаются по реакции акций
  ticker?: string;
  inn?: string;
  website?: string;
  // заполнен сервисом и ещё не проверен пользователем
  autofilled?: boolean;
  autofill_info?: { template?: string | null; from_description?: Record<string, string[]>; sources?: string[];
    sources_log?: SourceLogItem[] };
  is_demo?: boolean;
  updated_at?: string;
}

export interface SourceLogItem {
  source: string;
  status: "ok" | "empty" | "error";
  detail: string;
}

export type ProfileListField =
  | "subindustries" | "regions" | "products" | "clients" | "suppliers" | "competitors"
  | "goals" | "priorities" | "risks" | "investment_plans" | "keywords";

export interface FieldOptions {
  suggested: string[];
  other: string[];
}

export interface ProfileOptions {
  industries: string[];
  template: string | null;
  fields: Record<ProfileListField, FieldOptions>;
}

export interface ProfileSuggestion {
  profile: Omit<Profile, "id">;
  template: string | null;
  from_description: Record<string, string[]>;
}

export interface MarketReaction {
  ticker: string;
  ar: number;
  z: number;
  t0: string;
  t_end: string;
  relevant: boolean | null;
  impact_type: string | null;
  horizon: number;
}

export interface CompanyLookup {
  suggestion: ProfileSuggestion;
  registry: null | { source: string; inn: string; ogrn: string; name: string; region: string; registered: string | null };
  site: null | { source: string; url: string; title: string; description: string };
  errors: string[];
  sources_log: SourceLogItem[];
}

export interface Feedback {
  relevant: boolean | null;
  impact_type: "risk" | "opportunity" | "neutral" | null;
  priority: "higher" | "ok" | "lower" | null;
  updated_at?: string;
}

export interface ModelFeature {
  name: string;
  label: string;
  weight: number;
}

export interface ModelCv {
  folds: number;
  model_accuracy: number;
  rules_accuracy: number;
}

export interface ModelStatus {
  enabled: boolean;
  trained: boolean;
  active: boolean;
  impact_trained: boolean;
  weight: number;
  max_weight: number;
  min_labels: number;
  full_weight_at: number;
  labels: { total: number; relevance: number; relevant: number; not_relevant: number; impact: number; priority: number };
  by_profile: { profile_id: string; name: string; count: number }[];
  relevance: null | {
    n: number; positive: number; negative: number; n_user?: number; n_market?: number; cv: ModelCv | null; trained_at: string;
    top: { positive: ModelFeature[]; negative: ModelFeature[] };
  };
  impact: null | { n: number; classes: Record<string, number>; cv: ModelCv | null; trained_at: string };
  auto_max_weight: number;
  market: {
    labels: number; significant: number; quiet: number; ambiguous: number; by_origin: Record<string, number>;
    tickers: string[]; prices_until: string | null; horizon: number; significant_z: number; quiet_z: number;
    weight: number; quiet_weight: number; quiet_max_rule_relevance: number;
    examples: { event_id: string; title: string; company: string; ticker: string; ar: number; z: number;
      impact_type: string | null; t0: string; origin: string }[];
  };
}

export interface Verification {
  score: number;
  level: "high" | "medium" | "low";
  label: string;
  independent: number;
}

export interface VerificationDetail extends Verification {
  outlets: { name: string; source: string; country: string | null; tier: string | null; tier_label: string;
    reputation: number; holding: string; official: boolean; url: string | null }[];
  factors: Factor[];
}

export interface Outlet {
  name: string;
  country: string;
  tier: string;
  tier_label: string;
  reputation: number;
  holding: string;
  rss: boolean;
}

export interface FactStatus {
  code: "demo" | "confirmed" | "official" | "single" | "suspicious";
  label: string;
}

export interface EventCard {
  id: string;
  title: string;
  summary: string;
  source: string;
  source_type: string;
  url: string | null;
  published_at: string;
  is_demo: boolean;
  category: string;
  category_label: string;
  title_original: string | null;
  paraphrase: boolean;
  time_approx: boolean;
  regions: string[];
  priority: number;
  priority_level: Level;
  relevance: number;
  impact: number;
  urgency: number;
  urgency_level: Level;
  confidence: number;
  impact_type: ImpactType;
  summary_line: string;
  horizon_label: string;
  fact_status: FactStatus;
  verification: Verification;
  suspicious: boolean;
  related_count: number;
  favorite: boolean;
}

export interface Factor {
  key?: string;
  label: string;
  points: number;
  detail?: string;
}

export interface Score {
  priority: number;
  priority_level: Level;
  relevance: number;
  impact: number;
  urgency: number;
  urgency_level: Level;
  confidence: number;
  novelty: number;
  formula: string;
  contributions: { label: string; value: number; weight: number; points: number }[];
  adjustments: Factor[];
  relevance_factors: Factor[];
  impact_factors: Factor[];
  urgency_factors: Factor[];
  confidence_factors: Factor[];
}

export interface InsightItem {
  title: string;
  description: string;
  area: string;
  severity: "high" | "medium" | "low";
}

export interface SuggestedAction {
  title: string;
  description: string;
  // почему это важно / к чему приведёт, если сделать / что будет, если не сделать
  why?: string;
  if_done?: string;
  if_ignored?: string;
  owner: string;
  due_days: number;
  due_date: string;
  priority: "high" | "medium" | "low";
}

export interface Insight {
  engine: "rules" | "llm";
  model?: string;
  summary_line: string;
  what_happened: string;
  facts: string[];
  company_link: { element: string; value: string }[];
  causal_chain: string[][];
  risks: InsightItem[];
  opportunities: InsightItem[];
  impact_type: ImpactType;
  horizon: string;
  horizon_label: string;
  urgency: Level;
  actions: SuggestedAction[];
  indicators: string[];
  assumptions: string[];
  data_gaps: string[];
  confidence: number;
}

export interface EventDetail extends EventCard {
  body: string;
  rules_relevance: number;
  verification_detail: VerificationDetail;
  feedback: Feedback | null;
  market: MarketReaction | null;
  ml: { p_relevant?: number; weight?: number; impact_hint?: { type: string; p: number } };
  score: Score;
  insight: Insight;
  rules_insight: Insight;
  llm: { enabled: boolean; cached: boolean; stale: boolean; created_at?: string };
  linked_actions: number;
  linked_action_titles: string[];
  related: { id: string; title: string; source: string; url: string | null; published_at: string }[];
}

export interface CompareRow {
  profile_id: string;
  profile_name: string;
  industry: string;
  priority: number;
  priority_level: Level;
  relevance: number;
  urgency_level: Level;
  impact_type: ImpactType;
  summary_line: string;
  top_factors: Factor[];
}

export interface Action {
  id: number;
  profile_id: string;
  event_id: string | null;
  event_title?: string | null;
  event_is_demo?: number | null;
  title: string;
  description: string;
  priority: "high" | "medium" | "low";
  due_date: string | null;
  status: "new" | "in_progress" | "done";
  comment: string;
  owner: string;
  why?: string | null;
  if_done?: string | null;
  if_ignored?: string | null;
  created_at: string;
  updated_at: string;
}

export interface HistoryItem {
  id: number;
  action_id: number;
  ts: string;
  what: string;
  what_label: string;
  old_value: string | null;
  new_value: string | null;
}

export type TrendKind = "risk" | "opportunity" | "neutral";

export interface TrendPoint {
  day: string;
  risk: number;
  opportunity: number;
  neutral: number;
  events: Record<TrendKind, { id: string; title: string; priority: number }[]>;
}

export interface Overview {
  profile: { id: string; name: string };
  days: number;
  kpi: {
    total: number;
    relevant: number;
    important: number;
    critical_risks: number;
    risks: number;
    opportunities: number;
    attention: number;
  };
  trend: TrendPoint[];
  trend_step: "day" | "week";
  categories: { key: string; label: string; count: number; avg_priority: number }[];
  entities: { name: string; count: number }[];
  top_events: EventCard[];
  attention: EventCard[];
  opportunities: EventCard[];
  pending_actions: Action[];
}

export interface Status {
  data_mode: "curated" | "synthetic" | "live" | "mixed";
  dataset: "real" | "synthetic";
  curated_period: { from: string; to: string } | null;
  events: { curated: number; demo: number; live: number; total: number };
  llm: { enabled: boolean; model: string | null; note: string | null };
  model: { active: boolean; trained: boolean; enabled: boolean; weight: number; labels: number; min_labels: number };
  deleted_presets: { id: string; name: string }[];
  alfa: { configured: boolean; status: string };
  sources: { name: string; url: string; enabled: boolean; country: string; reputation: number; tier: string }[];
  companies: number;
  live: {
    last: null | { ts: string; ru_added: number; foreign_added: number; foreign_share: number; sources_ok: number;
      sources_failed: number };
    by_country: Record<string, number>;
    outlets: number;
  };
  fetch_log: { id: number; ts: string; source: string; ok: number; items: number; error: string | null }[];
}

export interface Meta {
  categories: { key: string; label: string }[];
  levels: { key: Level; label: string }[];
  impact_types: { key: string; label: string }[];
}
