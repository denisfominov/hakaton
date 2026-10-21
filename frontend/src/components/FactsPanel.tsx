import { Database } from "lucide-react";
import { api } from "../api";
import { useLoad } from "../context";
import type { ProfileFact } from "../types";
import { ErrorBox, Loading } from "./States";

// сервис 1 (C20.3): профиль только из набора банка — у каждого факта статус и источник (файл, запись, поля)
const GROUPS: Record<string, string> = {
  identity: "Компания", industry: "Отрасль и деятельность", scale: "Масштаб", position: "Положение в отрасли",
  group: "Группа компаний", bank_products: "Продукты банка", foreign_trade: "Внешнеэкономическая деятельность",
  geography: "География", counterparties: "Платежи: с кем компания связана", affiliates: "Связанные лица и компании",
  data_quality: "Качество данных",
};
const STATUS: Record<ProfileFact["status"], { label: string; cls: string }> = {
  confirmed: { label: "из данных", cls: "bg-emerald-50 text-emerald-800" },
  derived: { label: "рассчитано", cls: "bg-sky-50 text-sky-800" },
  no_data: { label: "нет данных", cls: "bg-ink-100 text-ink-500" },
  insufficient_data: { label: "недостаточно данных", cls: "bg-amber-50 text-amber-800" },
};

const pct = (v: number) => `${(v * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
const rub = (v: number) => (v >= 1e9 ? `${(v / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд ₽`
  : `${(v / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн ₽`);

function show(f: ProfileFact): string {
  const v = f.value as any;
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return f.label.includes("₽") ? rub(v) : f.label.includes("доля") ? pct(v) : v.toLocaleString("ru-RU");
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    if (!v.length) return "нет";
    return v.map((x) => (typeof x === "string" ? x : `${x.id}${x.okved_name ? ` (${x.okved_name.slice(0, 50)})` : ""}${
      x.share !== undefined ? ` — ${pct(x.share)}` : ""}`)).join("; ");
  }
  if (v.label) return v.label;
  if (v.rank !== undefined) return `${v.rank}-е место из ${v.of} · ${pct(v.share_in_sample)} выручки выборки`;
  if (v.above !== undefined) return `${v.above ? "да" : "нет"} (${v.basis}: ${rub(v.revenue)})`;
  if (v.companies !== undefined) return v.companies ? `${v.companies} компаний` : "нет";
  return Object.entries(v).map(([k, s]) => `${k} ${pct(s as number)}`).join(" · ");
}

export default function FactsPanel({ profileId }: { profileId: string }) {
  const { data, loading, error } = useLoad(() => api.profileFacts(profileId), [profileId]);
  if (loading && !data) return <Loading text="Собираем профиль из данных банка…" />;
  if (error) return error.includes("нет в наборе") ? null : <ErrorBox error={error} />;
  if (!data) return null;
  const groups = Object.keys(GROUPS).filter((g) => data.facts.some((f) => f.group === g));
  return (
    <section className="card p-5">
      <h2 className="section-title flex items-center gap-2"><Database size={15} className="text-ink-500" /> Профиль из данных банка</h2>
      <p className="mt-1 text-xs text-ink-500">
        Только набор данных Альфа-Банка ({data.dataset === "sample" ? "синтетический пример" : "данные кейса"}): новости,
        сайты и знания модели не используются. У каждого факта — файл, запись и поле; пропуски не заполняются догадками.
        Пробелов: {data.gaps.length}.
      </p>
      <div className="mt-4 space-y-4">
        {groups.map((g) => (
          <div key={g}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">{GROUPS[g]}</h3>
            <ul className="mt-1 divide-y divide-ink-100">
              {data.facts.filter((f) => f.group === g).map((f) => (
                <li key={f.id} className="py-1.5 text-sm">
                  <details>
                    <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-2 gap-y-1">
                      <span className="text-ink-500">{f.label}:</span>
                      <span className="font-medium text-ink-900">{show(f)}</span>
                      <span className={`rounded px-1.5 py-0.5 text-[11px] ${STATUS[f.status].cls}`}>{STATUS[f.status].label}</span>
                      {data.significance_facts.includes(f.id) && (
                        <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[11px] text-violet-800" title="может влиять на значимость новостей">
                          влияет на значимость
                        </span>
                      )}
                    </summary>
                    <div className="mt-1 space-y-0.5 pl-1 text-xs text-ink-500">
                      {f.sources.map((s, i) => (
                        <p key={i}>Источник: {s.file} · {s.record} · поля {s.fields.join(", ")}</p>
                      ))}
                      {f.method && <p>Как рассчитано: {f.method}</p>}
                      {f.note && <p>Оговорка: {f.note}</p>}
                      <p className="text-ink-400">{f.id}</p>
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
