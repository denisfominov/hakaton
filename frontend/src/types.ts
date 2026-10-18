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
  is_demo?: boolean;
  updated_at?: string;
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
  trend: { day: string; risk: number; opportunity: number; neutral: number }[];
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
  alfa: { configured: boolean; status: string };
  sources: { name: string; url: string; enabled: boolean }[];
  fetch_log: { id: number; ts: string; source: string; ok: number; items: number; error: string | null }[];
}

export interface Meta {
  categories: { key: string; label: string }[];
  levels: { key: Level; label: string }[];
  impact_types: { key: string; label: string }[];
}
