import { ArrowRight, Info } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ImpactBadge } from "../components/Badges";
import { ErrorBox, Skeleton } from "../components/States";
import { useApp, useLoad } from "../context";

const PERIODS = [
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
];

// цвет ячейки тепловой карты — как шкала приоритета
function heatCls(v: number) {
  if (v >= 70) return "bg-rose-600 text-white";
  if (v >= 50) return "bg-orange-400 text-white";
  if (v >= 30) return "bg-amber-200 text-amber-900";
  if (v > 0) return "bg-ink-100 text-ink-700";
  return "text-ink-300";
}

// портфель: все компании сразу — кому звонить первым и в каких темах риски
export default function PortfolioPage() {
  const { setProfileId, bumpData } = useApp();
  const navigate = useNavigate();
  const [days, setDays] = useState(7);
  const { data, loading, error, reload } = useLoad(() => api.portfolio(days), [days]);

  const open = (pid: string, to: string) => {
    setProfileId(pid);
    bumpData();
    navigate(to);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Портфель компаний</h1>
          <p className="mt-1 text-sm text-ink-500">Все компании сразу: кому из клиентов звонить первым и в каких темах риски</p>
        </div>
        <div className="inline-flex self-start rounded-lg border border-ink-200 bg-white p-0.5 sm:self-auto">
          {PERIODS.map((p) => (
            <button key={p.days} onClick={() => setDays(p.days)}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${days === p.days ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-ink-100"}`}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton rows={4} />}

      {data && (
        <>
          <section className={`card overflow-hidden ${loading ? "opacity-60" : ""}`}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="border-b border-ink-200 bg-ink-50 text-left text-xs text-ink-500">
                    <th className="px-4 py-2.5 font-medium">Компания</th>
                    <th className="px-3 py-2.5 font-medium" title={data.formula}>Индекс внимания</th>
                    <th className="px-3 py-2.5 text-right font-medium">Крит. риски</th>
                    <th className="px-3 py-2.5 text-right font-medium">Риски</th>
                    <th className="px-3 py-2.5 text-right font-medium">Возможности</th>
                    <th className="px-3 py-2.5 text-right font-medium">Срочно</th>
                    <th className="px-4 py-2.5 font-medium">Главное событие</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {data.rows.map((r, i) => (
                    <tr key={r.profile_id} className="align-top hover:bg-ink-50/60">
                      <td className="px-4 py-3">
                        <button className="text-left font-medium text-ink-900 hover:underline" onClick={() => open(r.profile_id, "/")}>
                          {i + 1}. {r.name}
                        </button>
                        <div className="text-xs text-ink-500">{r.industry || "—"}</div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <span className="block h-2 w-20 rounded-full bg-ink-100">
                            <span className={`block h-2 rounded-full ${r.attention_index >= 70 ? "bg-rose-600" : r.attention_index >= 50 ? "bg-orange-400" : "bg-ink-400"}`}
                              style={{ width: `${r.attention_index}%` }} />
                          </span>
                          <span className="font-semibold tabular-nums">{r.attention_index}</span>
                        </div>
                      </td>
                      <td className={`px-3 py-3 text-right tabular-nums ${r.critical_risks ? "font-semibold text-rose-700" : "text-ink-400"}`}>{r.critical_risks}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{r.risks}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-emerald-700">{r.opportunities}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{r.attention}</td>
                      <td className="max-w-[340px] px-4 py-3">
                        {r.top_event ? (
                          <button className="group text-left" onClick={() => open(r.profile_id, `/events/${r.top_event!.id}`)}>
                            <div className="flex items-center gap-2">
                              <span className="rounded bg-ink-900 px-1.5 text-xs font-semibold tabular-nums text-white">{r.top_event.priority}</span>
                              <ImpactBadge type={r.top_event.impact_type} />
                            </div>
                            <div className="mt-1 line-clamp-2 text-ink-900 group-hover:underline">{r.top_event.title}</div>
                            <div className="mt-0.5 line-clamp-1 text-xs text-ink-500">{r.top_event.summary_line}</div>
                          </button>
                        ) : <span className="text-xs text-ink-400">Значимых событий за период нет</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="flex gap-1.5 border-t border-ink-100 px-4 py-2.5 text-xs text-ink-500">
              <Info size={13} className="mt-0.5 shrink-0" /> Сортировка — по индексу внимания: {data.formula}.
            </p>
          </section>

          {data.categories.length > 0 && (
            <section className="card p-4">
              <h2 className="section-title">Темы × компании</h2>
              <p className="text-xs text-ink-500">Максимальный приоритет событий темы для компании за период; нажмите на ячейку, чтобы открыть ленту</p>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[640px] border-separate border-spacing-1 text-xs">
                  <thead>
                    <tr>
                      <th />
                      {data.categories.map((c) => <th key={c.key} className="px-1 pb-1 text-center font-medium text-ink-500">{c.label}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr key={r.profile_id}>
                        <td className="whitespace-nowrap pr-2 text-sm text-ink-700">{r.name}</td>
                        {data.categories.map((c) => {
                          const h = r.heat[c.key];
                          return (
                            <td key={c.key} className="p-0">
                              {h ? (
                                <button className={`h-9 w-full rounded-md font-semibold tabular-nums ${heatCls(h.max)}`}
                                  title={`${c.label}: ${h.n} событий, максимум ${h.max}`}
                                  onClick={() => open(r.profile_id, `/feed?category=${c.key}&days=${days}&sort=priority`)}>
                                  {h.max}<span className="ml-1 font-normal opacity-75">· {h.n}</span>
                                </button>
                              ) : <div className="h-9 rounded-md bg-ink-50" />}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <Link to="/companies" className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-ink-900">
            Добавить или убрать компании в «Выборе компании» <ArrowRight size={14} />
          </Link>
        </>
      )}
    </div>
  );
}
