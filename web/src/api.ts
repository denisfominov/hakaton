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

export function getCompanies(filter: CompanyFilter) {
  const query = new URLSearchParams({ limit: String(filter.limit), offset: String(filter.offset) });
  if (filter.large) query.set("large", "true");
  if (filter.region) query.set("region", filter.region);
  if (filter.okved.trim()) query.set("okved", filter.okved.trim());
  return getJson<CompanyPage>(`/companies?${query}`);
}
