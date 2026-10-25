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

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

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
