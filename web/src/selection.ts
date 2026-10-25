export const roles = ["owner", "ceo", "cfo", "treasurer", "accountant"] as const;

export type Role = (typeof roles)[number];

export type Selection = { companyId: string; role: Role };

const KEY = "insights.selection";

export function loadSelection(): Selection | null {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return value && typeof value.companyId === "string" && roles.includes(value.role) ? value : null;
  } catch {
    return null;
  }
}

export function saveSelection(selection: Selection | null) {
  try {
    if (selection) localStorage.setItem(KEY, JSON.stringify(selection));
    else localStorage.removeItem(KEY);
  } catch {
    return;
  }
}
