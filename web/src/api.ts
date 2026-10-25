export type Health = {
  status: string;
  companies: number;
  links: number;
  payments: number;
};

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const getHealth = () => getJson<Health>("/health");
