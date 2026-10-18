import type { ImpactType, Level } from "./types";

export const LEVEL_LABEL: Record<Level, string> = {
  critical: "Критический",
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};

export const URGENCY_LABEL: Record<Level, string> = {
  critical: "Реагировать сегодня",
  high: "В течение недели",
  medium: "В течение месяца",
  low: "Мониторинг",
};

export const IMPACT_LABEL: Record<ImpactType, string> = {
  risk: "Риск",
  opportunity: "Возможность",
  mixed: "Риск и возможность",
  neutral: "Нейтрально",
};

export const AREA_LABEL: Record<string, string> = {
  financial: "Финансы",
  operational: "Операции",
  regulatory: "Регулирование",
  strategic: "Стратегия",
  market: "Рынок",
};

export const PRIORITY_LABEL: Record<string, string> = { high: "Высокий", medium: "Средний", low: "Низкий" };
export const STATUS_LABEL: Record<string, string> = { new: "Новое", in_progress: "В работе", done: "Выполнено" };

// цвета держим в одном месте, чтобы бейджи и графики совпадали
export const levelColor: Record<Level, string> = {
  critical: "bg-red-600",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-ink-300",
};

export const levelText: Record<Level, string> = {
  critical: "text-red-700",
  high: "text-orange-600",
  medium: "text-amber-700",
  low: "text-ink-500",
};

export function formatDate(iso: string | null | undefined, withTime = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))} мин назад`;
  if (diff < 86400) return `${Math.round(diff / 3600)} ч назад`;
  const days = Math.round(diff / 86400);
  if (days < 7) return `${days} дн. назад`;
  return formatDate(iso, false);
}

export function isOverdue(date: string | null, status: string) {
  if (!date || status === "done") return false;
  return new Date(date) < new Date(new Date().toDateString());
}

export function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}
