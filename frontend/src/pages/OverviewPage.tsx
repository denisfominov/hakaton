import { ArrowRight, CalendarClock, FlaskConical, Lightbulb, ShieldAlert, Siren, Sparkles, Target } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { ImpactBadge, LevelBadge, PriorityScore, UrgencyBadge } from "../components/Badges";
import { Empty, ErrorBox, Skeleton } from "../components/States";
import { useApp, useLoad } from "../context";
import type { EventCard } from "../types";
import { PRIORITY_LABEL, formatDate, isOverdue, timeAgo } from "../utils";

const PERIODS = [
  { days: 1, label: "24 часа" },
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
];

function Kpi({ label, value, hint, icon: Icon, tone, onClick }: {
  label: string; value: number; hint: string; icon: typeof Siren; tone: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick} className="card group p-4 text-left transition hover:border-ink-300">
      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-500">{label}</span>
        <span className={`rounded-lg p-1.5 ${tone}`}><Icon size={16} /></span>
      </div>
      <div className="mt-2 text-3xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 flex items-center gap-1 text-xs text-ink-400 group-hover:text-ink-700">
        {hint} <ArrowRight size={12} />
      </div>
    </button>
  );
}

function EventRow({ ev }: { ev: EventCard }) {
  return (
    <Link to={`/events/${ev.id}`} className="flex gap-3 rounded-lg p-3 transition hover:bg-ink-50">
      <PriorityScore value={ev.priority} level={ev.priority_level} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <ImpactBadge type={ev.impact_type} />
          <UrgencyBadge level={ev.urgency_level} />
          <span className="text-xs text-ink-400">{ev.category_label} · {timeAgo(ev.published_at)}</span>
        </div>
        <p className="mt-1 font-medium leading-snug text-ink-900">{ev.title}</p>
        <p className="mt-0.5 text-sm text-ink-500">{ev.summary_line}</p>
      </div>
    </Link>
  );
}

export default function OverviewPage() {
  const { profileId, profile, dataVersion, meta, status } = useApp();
  const navigate = useNavigate();
  const [days, setDays] = useState(7);
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [impact, setImpact] = useState("");

  const { data, loading, error, reload } = useLoad(
    () => api.overview(profileId, { days, category, impact, level }),
    [profileId, days, category, impact, level, dataVersion],
  );

  const goFeed = (extra: Record<string, string>) => {
    const p = new URLSearchParams({ days: String(days), ...extra });
    if (category) p.set("category", category);
    navigate(`/feed?${p.toString()}`);
  };

  const hasFilters = category || level || impact;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Обзор для руководителя</h1>
          <p className="mt-1 text-sm text-ink-500">
            {profile?.name} · что произошло и на что обратить внимание
          </p>
        </div>
        <div className="inline-flex self-start rounded-lg border border-ink-200 bg-white p-0.5 sm:self-auto">
          {PERIODS.map((p) => (
            <button key={p.days} onClick={() => setDays(p.days)}
              className={`rounded-md px-3 py-1.5 text-sm ${days === p.days ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-ink-100"}`}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
          <select className="input !w-auto !py-1.5" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Категория">
            <option value="">Все категории</option>
            {meta?.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
          <select className="input !w-auto !py-1.5" value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Важность">
            <option value="">Любая важность</option>
            <option value="critical">Только критические</option>
            <option value="high">Высокая и выше</option>
            <option value="medium">Средняя и выше</option>
          </select>
          <select className="input !w-auto !py-1.5" value={impact} onChange={(e) => setImpact(e.target.value)} aria-label="Тип влияния">
            <option value="">Риски и возможности</option>
            <option value="risk">Только риски</option>
            <option value="opportunity">Только возможности</option>
            <option value="neutral">Нейтральные</option>
          </select>
          {hasFilters && (
            <button className="btn-ghost" onClick={() => { setCategory(""); setLevel(""); setImpact(""); }}>Сбросить</button>
          )}
      </div>

      {status?.data_mode !== "live" && (
        <div className="flex items-start gap-3 rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
          <FlaskConical size={18} className="mt-0.5 shrink-0" />
          {status?.data_mode === "demo" ? (
            <p>
              <b>Демонстрационный режим.</b> События и компании синтетические, ссылок на оригиналы у них нет.
              Реальные новости из RSS можно загрузить кнопкой «Обновить ленту».
            </p>
          ) : (
            <p>
              <b>Смешанный режим:</b> демо-события (помечены «Демо») и реальные новости из RSS.
              Оставить только реальные можно фильтром источника в ленте.
            </p>
          )}
        </div>
      )}

      {error &&<ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton rows={3} />}

      {data && (
        <>
          <div className={`grid grid-cols-2 gap-3 lg:grid-cols-4 ${loading ? "opacity-60" : ""}`}>
            <Kpi label="Важные события" value={data.kpi.important} hint="Высокий и критический приоритет"
              icon={Target} tone="bg-ink-100 text-ink-700" onClick={() => goFeed({ level: "high" })} />
            <Kpi label="Критические риски" value={data.kpi.critical_risks} hint={`Всего рисков: ${data.kpi.risks}`}
              icon={ShieldAlert} tone="bg-rose-50 text-rose-700" onClick={() => goFeed({ impact: "risk", level: "high" })} />
            <Kpi label="Возможности" value={data.kpi.opportunities} hint="Для роста и экономии"
              icon={Lightbulb} tone="bg-emerald-50 text-emerald-700" onClick={() => goFeed({ impact: "opportunity" })} />
            <Kpi label="Требуют реакции" value={data.kpi.attention} hint="Срочность: сегодня / неделя"
              icon={Siren} tone="bg-orange-50 text-orange-700" onClick={() => goFeed({ sort: "urgency" })} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <section className="card p-2 lg:col-span-2">
              <div className="flex items-center justify-between px-3 pb-1 pt-3">
                <h2 className="section-title">Требует внимания в первую очередь</h2>
                <Link to="/feed" className="text-sm text-ink-500 hover:text-ink-900">Вся лента →</Link>
              </div>
              {data.top_events.length === 0 ? (
                <div className="p-6 text-sm text-ink-500">За выбранный период нет событий по этим фильтрам.</div>
              ) : (
                <div className="divide-y divide-ink-100">
                  {data.top_events.slice(0, 5).map((ev) => <EventRow key={ev.id} ev={ev} />)}
                </div>
              )}
            </section>

            <div className="space-y-6">
              <section className="card p-4">
                <div className="flex items-center justify-between">
                  <h2 className="section-title">Решения ждут</h2>
                  <Link to="/decisions" className="text-sm text-ink-500 hover:text-ink-900">Все →</Link>
                </div>
                {data.pending_actions.length === 0 ? (
                  <p className="mt-3 text-sm text-ink-500">
                    Пока нет действий. Откройте событие и добавьте рекомендацию в план.
                  </p>
                ) : (
                  <ul className="mt-3 space-y-3">
                    {data.pending_actions.map((a) => (
                      <li key={a.id} className="text-sm">
                        <Link to="/decisions" className="font-medium text-ink-900 hover:underline">{a.title}</Link>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-ink-500">
                          <span>{PRIORITY_LABEL[a.priority]} приоритет</span>
                          {a.due_date && (
                            <span className={`inline-flex items-center gap-1 ${isOverdue(a.due_date, a.status) ? "text-red-600" : ""}`}>
                              <CalendarClock size={12} /> до {formatDate(a.due_date, false)}
                            </span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="card p-4">
                <h2 className="section-title flex items-center gap-2"><Sparkles size={15} className="text-emerald-600" /> Новые возможности</h2>
                {data.opportunities.length === 0 ? (
                  <p className="mt-3 text-sm text-ink-500">Возможностей за период не найдено.</p>
                ) : (
                  <ul className="mt-3 space-y-3">
                    {data.opportunities.map((ev) => (
                      <li key={ev.id}>
                        <Link to={`/events/${ev.id}`} className="block text-sm font-medium leading-snug hover:underline">{ev.summary_line}</Link>
                        <div className="mt-1"><LevelBadge level={ev.priority_level} prefix="Приоритет" /></div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <section className="card p-4 lg:col-span-2">
              <h2 className="section-title">Динамика повестки</h2>
              <p className="text-xs text-ink-500">События, связанные с компанией (релевантность от 25), по дням публикации</p>
              {data.trend.every((d) => !d.risk && !d.opportunity && !d.neutral) ? (
                <div className="py-12 text-center text-sm text-ink-500">Нет значимых событий за период</div>
              ) : (
                <div className="mt-4 h-60">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.trend.map((d) => ({ ...d, label: formatDate(d.day, false) }))} barCategoryGap="25%">
                      <CartesianGrid vertical={false} stroke="#eef1f4" />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} stroke="#94a3b8" />
                      <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} stroke="#94a3b8" width={28} />
                      <Tooltip cursor={{ fill: "#f1f5f9" }} contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 13 }} />
                      <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="risk" name="Риски" stackId="a" fill="#e11d48" />
                      <Bar dataKey="opportunity" name="Возможности" stackId="a" fill="#059669" />
                      <Bar dataKey="neutral" name="Нейтральные" stackId="a" fill="#cbd5e1" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>

            <section className="card p-4">
              <h2 className="section-title">Значимые темы</h2>
              {data.categories.length === 0 ? (
                <p className="mt-3 text-sm text-ink-500">Нет данных</p>
              ) : (
                <ul className="mt-3 space-y-2.5">
                  {data.categories.map((c) => (
                    <li key={c.key}>
                      <button className="w-full text-left" onClick={() => setCategory(c.key)} title="Отфильтровать по категории">
                        <div className="flex justify-between text-sm">
                          <span className="text-ink-700">{c.label}</span>
                          <span className="text-ink-400 tabular-nums">{c.count} · ср. {c.avg_priority}</span>
                        </div>
                        <div className="mt-1 h-1.5 rounded-full bg-ink-100">
                          <div className="h-1.5 rounded-full bg-ink-700" style={{ width: `${c.avg_priority}%` }} />
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {data.entities.length > 0 && (
                <>
                  <h3 className="mt-5 text-xs font-medium uppercase tracking-wide text-ink-500">Чаще всего в повестке</h3>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {data.entities.map((e) => (
                      <button key={e.name} onClick={() => navigate(`/feed?q=${encodeURIComponent(e.name)}&days=${days}`)}
                        className="rounded-md border border-ink-200 px-2 py-0.5 text-xs text-ink-700 hover:bg-ink-100">
                        {e.name} <span className="text-ink-400">{e.count}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </section>
          </div>

          {data.kpi.total === 0 && (
            <Empty title="За этот период событий нет" text="Попробуйте выбрать 30 дней или обновить ленту." />
          )}
        </>
      )}
    </div>
  );
}
