import { AlertTriangle, CheckCircle2, FlaskConical, Landmark, ShieldAlert, TrendingDown, TrendingUp, Minus, Shuffle } from "lucide-react";
import type { FactStatus, ImpactType, Level, Verification } from "../types";
import { IMPACT_LABEL, LEVEL_LABEL, URGENCY_LABEL, levelColor, levelText } from "../utils";

export function PriorityScore({ value, level, size = "md" }: { value: number; level: Level; size?: "md" | "lg" }) {
  const big = size === "lg";
  return (
    <div className={`flex flex-col items-center justify-center rounded-lg border border-ink-200 bg-white ${big ? "h-20 w-20" : "h-12 w-12"}`}
      title={`Приоритет ${value}/100 — ${LEVEL_LABEL[level]}`}>
      <span className={`${big ? "text-3xl" : "text-lg"} font-semibold leading-none tabular-nums ${levelText[level]}`}>{value}</span>
      <span className={`mt-1 h-1 rounded-full ${levelColor[level]} ${big ? "w-10" : "w-6"}`} />
    </div>
  );
}

export function LevelBadge({ level, prefix }: { level: Level; prefix?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-ink-100 px-2 py-0.5 text-xs font-medium text-ink-700">
      <span className={`h-2 w-2 rounded-full ${levelColor[level]}`} />
      {prefix ? `${prefix}: ` : ""}
      {LEVEL_LABEL[level]}
    </span>
  );
}

export function UrgencyBadge({ level }: { level: Level }) {
  const strong = level === "critical" || level === "high";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${
      strong ? "bg-red-50 text-red-700" : "bg-ink-100 text-ink-500"}`}>
      {strong && <AlertTriangle size={12} />}
      {URGENCY_LABEL[level]}
    </span>
  );
}

const impactStyle: Record<ImpactType, string> = {
  risk: "bg-rose-50 text-rose-700 ring-rose-200",
  opportunity: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  mixed: "bg-amber-50 text-amber-800 ring-amber-200",
  neutral: "bg-ink-100 text-ink-500 ring-ink-200",
};

const impactIcon = {
  risk: TrendingDown,
  opportunity: TrendingUp,
  mixed: Shuffle,
  neutral: Minus,
};

export function ImpactBadge({ type }: { type: ImpactType }) {
  const Icon = impactIcon[type];
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${impactStyle[type]}`}>
      <Icon size={12} />
      {IMPACT_LABEL[type]}
    </span>
  );
}

export function FactBadge({ status }: { status: FactStatus }) {
  const map = {
    demo: { cls: "text-violet-700 bg-violet-50", Icon: FlaskConical },
    confirmed: { cls: "text-emerald-700 bg-emerald-50", Icon: CheckCircle2 },
    official: { cls: "text-sky-700 bg-sky-50", Icon: Landmark },
    single: { cls: "text-ink-500 bg-ink-100", Icon: AlertTriangle },
    suspicious: { cls: "text-red-700 bg-red-50", Icon: ShieldAlert },
  }[status.code];
  const Icon = map.Icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${map.cls}`} title="Статус проверки фактов">
      <Icon size={12} />
      {status.label}
    </span>
  );
}

export function DemoBadge() {
  return (
    <span className="rounded bg-violet-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
      title="Синтетическое событие из демонстрационного набора — не реальная новость">
      Демо
    </span>
  );
}

export function Meter({ value, label, tone = "ink" }: { value: number; label: string; tone?: "ink" | "brand" }) {
  return (
    <div className="min-w-[110px]">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-ink-500">{label}</span>
        <span className="font-medium tabular-nums text-ink-700">{value}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-ink-100">
        <div className={`h-1.5 rounded-full ${tone === "brand" ? "bg-brand" : "bg-ink-700"}`} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}


// достоверность: репутация издания + независимые подтверждения (backend/app/outlets.py)
export function VerificationBadge({ v, status }: { v: Verification; status: FactStatus }) {
  if (status.code === "demo" || status.code === "suspicious") return <FactBadge status={status} />;
  const cls = { high: "text-emerald-700 bg-emerald-50", medium: "text-amber-800 bg-amber-50", low: "text-ink-500 bg-ink-100" }[v.level];
  const Icon = v.level === "low" ? AlertTriangle : CheckCircle2;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}
      title={`Достоверность ${v.score} из 100: репутация издания и подтверждения в других изданиях`}>
      <Icon size={12} />
      Достоверность {v.score}{v.independent > 1 ? ` · ${v.independent} изд.` : " · 1 источник"}
    </span>
  );
}
