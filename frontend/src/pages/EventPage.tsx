import {
  ArrowLeft, ArrowRight, Bot, Check, ChevronDown, ExternalLink, Eye, FileText, Info, Plus, ShieldAlert, Star,
} from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import ActionForm from "../components/ActionForm";
import type { ActionDraft } from "../components/ActionForm";
import { DemoBadge, FactBadge, ImpactBadge, LevelBadge, PriorityScore, UrgencyBadge } from "../components/Badges";
import Modal from "../components/Modal";
import { ErrorBox, Loading } from "../components/States";
import { useApp, useLoad } from "../context";
import type { EventDetail, Factor, Insight, InsightItem, Score, SuggestedAction } from "../types";
import { AREA_LABEL, LEVEL_LABEL, PRIORITY_LABEL, URGENCY_LABEL, formatDate, levelText } from "../utils";

function Block({ n, title, children, hint }: { n: number; title: string; children: ReactNode; hint?: string }) {
  return (
    <section className="border-t border-ink-100 px-5 py-5 first:border-t-0">
      <h3 className="flex items-baseline gap-2 font-semibold">
        <span className="text-xs font-medium tabular-nums text-ink-400">{String(n).padStart(2, "0")}</span>
        {title}
      </h3>
      {hint && <p className="mt-0.5 text-xs text-ink-500">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function ItemList({ items, tone, empty }: { items: InsightItem[]; tone: "risk" | "opp"; empty: string }) {
  if (!items.length) return <p className="text-sm text-ink-500">{empty}</p>;
  const border = tone === "risk" ? "border-l-rose-500" : "border-l-emerald-500";
  return (
    <ul className="space-y-2">
      {items.map((it, i) => (
        <li key={i} className={`rounded-lg border border-l-4 border-ink-200 ${border} bg-white px-4 py-3`}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{it.title}</span>
            <span className="rounded bg-ink-100 px-1.5 py-0.5 text-xs text-ink-500">{AREA_LABEL[it.area] || it.area}</span>
            <span className="text-xs text-ink-500">сила: {PRIORITY_LABEL[it.severity]?.toLowerCase()}</span>
          </div>
          <p className="mt-1 text-sm text-ink-700">{it.description}</p>
        </li>
      ))}
    </ul>
  );
}

function FactorList({ factors }: { factors: Factor[] }) {
  if (!factors.length) return <p className="text-xs text-ink-400">Нет факторов</p>;
  return (
    <ul className="space-y-1.5">
      {factors.map((f, i) => (
        <li key={i} className="flex gap-2 text-sm">
          <span className={`w-10 shrink-0 text-right font-medium tabular-nums ${f.points >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
            {f.points > 0 ? "+" : ""}{f.points}
          </span>
          <span className="min-w-0">
            <span className="text-ink-900">{f.label}</span>
            {f.detail && <span className="block text-xs text-ink-500">{f.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function ScorePanel({ score, profileName }: { score: Score; profileName?: string }) {
  const [open, setOpen] = useState<string | null>("relevance");
  const rows: { key: string; label: string; value: number; extra?: string; factors: Factor[] }[] = [
    { key: "relevance", label: "Релевантность", value: score.relevance, factors: score.relevance_factors },
    { key: "impact", label: "Потенциальное влияние", value: score.impact, factors: score.impact_factors },
    { key: "urgency", label: "Срочность", value: score.urgency, extra: URGENCY_LABEL[score.urgency_level], factors: score.urgency_factors },
    { key: "confidence", label: "Уверенность в выводе", value: score.confidence, factors: score.confidence_factors },
  ];
  return (
    <div className="card p-5">
      <div className="flex items-center gap-4">
        <PriorityScore value={score.priority} level={score.priority_level} size="lg" />
        <div>
          <div className="text-xs uppercase tracking-wide text-ink-500">Приоритет для компании</div>
          <div className={`text-lg font-semibold ${levelText[score.priority_level]}`}>{LEVEL_LABEL[score.priority_level]}</div>
          <div className="text-xs text-ink-500">{profileName}</div>
        </div>
      </div>

      <div className="mt-5">
        <div className="text-xs font-medium uppercase tracking-wide text-ink-500">Из чего сложился балл</div>
        <ul className="mt-2 space-y-1 text-sm">
          {score.contributions.map((c) => (
            <li key={c.label} className="flex justify-between">
              <span className="text-ink-700">{c.label} <span className="text-ink-400">{c.value} × {c.weight}</span></span>
              <span className="tabular-nums text-ink-900">{c.points}</span>
            </li>
          ))}
          {score.adjustments.map((a) => (
            <li key={a.label} className="flex justify-between text-rose-700">
              <span>{a.label}</span><span className="tabular-nums">{a.points}</span>
            </li>
          ))}
          <li className="flex justify-between border-t border-ink-100 pt-1 font-semibold">
            <span>Итог</span><span className="tabular-nums">{score.priority}</span>
          </li>
        </ul>
        <p className="mt-2 text-[11px] leading-snug text-ink-400">{score.formula}. Экспертная шкала 0–100, а не вероятность убытка.</p>
      </div>

      <div className="mt-5 space-y-1">
        {rows.map((r) => (
          <div key={r.key} className="rounded-lg border border-ink-100">
            <button className="flex w-full items-center gap-3 px-3 py-2 text-left" onClick={() => setOpen(open === r.key ? null : r.key)}>
              <span className="flex-1 text-sm">
                {r.label}
                {r.extra && <span className="block text-xs text-ink-500">{r.extra}</span>}
              </span>
              <span className="w-16">
                <span className="block h-1.5 rounded-full bg-ink-100">
                  <span className="block h-1.5 rounded-full bg-ink-700" style={{ width: `${r.value}%` }} />
                </span>
              </span>
              <span className="w-7 text-right text-sm font-medium tabular-nums">{r.value}</span>
              <ChevronDown size={14} className={`text-ink-400 transition ${open === r.key ? "rotate-180" : ""}`} />
            </button>
            {open === r.key && <div className="border-t border-ink-100 px-3 py-3"><FactorList factors={r.factors} /></div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function ActionsBlock({ actions, added, onAdd }: { actions: SuggestedAction[]; added: Set<string>; onAdd: (a: SuggestedAction) => void }) {
  if (!actions.length) return <p className="text-sm text-ink-500">Конкретных действий не требуется.</p>;
  return (
    <ul className="space-y-2">
      {actions.map((a) => (
        <li key={a.title} className="flex flex-col gap-3 rounded-lg border border-ink-200 px-4 py-3 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <div className="font-medium">{a.title}</div>
            <p className="mt-0.5 text-sm text-ink-700">{a.description}</p>
            <div className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-ink-500">
              <span>Ответственный: {a.owner}</span>
              <span>Срок: {a.due_days} дн. (до {formatDate(a.due_date, false)})</span>
              <span>Приоритет: {PRIORITY_LABEL[a.priority]?.toLowerCase()}</span>
            </div>
          </div>
          {added.has(a.title) ? (
            <Link to="/decisions" className="btn-secondary shrink-0 !text-emerald-700"><Check size={15} /> В плане</Link>
          ) : (
            <button className="btn-secondary shrink-0" onClick={() => onAdd(a)}><Plus size={15} /> В план действий</button>
          )}
        </li>
      ))}
    </ul>
  );
}

function Analysis({ ins, ev, added, onAdd }: { ins: Insight; ev: EventDetail; added: Set<string>; onAdd: (a: SuggestedAction) => void }) {
  return (
    <>
      <Block n={1} title="Суть события"
        hint={ev.paraphrase ? "Что фактически произошло — по пересказу публикации (оригинал по ссылке)" : "Что фактически произошло — по тексту источника"}>
        <p className="text-sm text-ink-900">{ins.what_happened}</p>
        {ins.facts.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {ins.facts.map((f, i) => (
              <li key={i} className="flex gap-2 text-sm text-ink-700">
                <Check size={14} className="mt-0.5 shrink-0 text-emerald-600" /> {f}
              </li>
            ))}
          </ul>
        )}
      </Block>

      <Block n={2} title="Связь с компанией" hint="Какие элементы профиля делают новость важной">
        {ins.company_link.length === 0 ? (
          <p className="text-sm text-ink-500">Совпадений с профилем не найдено — событие слабо относится к компании.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {ins.company_link.map((l, i) => (
              <span key={i} className="rounded-lg border border-ink-200 bg-ink-50 px-2.5 py-1 text-sm">
                <span className="text-ink-500">{l.element}:</span> <span className="font-medium">{l.value}</span>
              </span>
            ))}
          </div>
        )}
      </Block>

      <Block n={3} title="Как событие влияет на бизнес" hint="Причинно-следственная цепочка">
        {ins.causal_chain.length === 0 ? (
          <p className="text-sm text-ink-500">Прямой канал влияния не выявлен.</p>
        ) : (
          <div className="space-y-2">
            {ins.causal_chain.map((chain, i) => (
              <div key={i} className="flex flex-wrap items-center gap-1.5 text-sm">
                {chain.map((step, j) => (
                  <span key={j} className="flex items-center gap-1.5">
                    <span className={`rounded-md px-2 py-1 ${j === chain.length - 1 ? "bg-ink-900 text-white" : "bg-ink-100 text-ink-700"}`}>{step}</span>
                    {j < chain.length - 1 && <ArrowRight size={14} className="text-ink-400" />}
                  </span>
                ))}
              </div>
            ))}
          </div>
        )}
      </Block>

      <Block n={4} title="Риски">
        <ItemList items={ins.risks} tone="risk" empty="Рисков для компании не выявлено." />
      </Block>

      <Block n={5} title="Возможности">
        <ItemList items={ins.opportunities} tone="opp" empty="Возможностей для компании не выявлено." />
      </Block>

      <section className="grid gap-px border-t border-ink-100 bg-ink-100 sm:grid-cols-2">
        <div className="bg-white px-5 py-5">
          <h3 className="flex items-baseline gap-2 font-semibold"><span className="text-xs text-ink-400">06</span> Горизонт влияния</h3>
          <p className="mt-2 text-lg font-medium">{ins.horizon_label}</p>
        </div>
        <div className="bg-white px-5 py-5">
          <h3 className="flex items-baseline gap-2 font-semibold"><span className="text-xs text-ink-400">07</span> Срочность реакции</h3>
          <div className="mt-2 flex items-center gap-2">
            <LevelBadge level={ins.urgency} />
            <span className="text-sm text-ink-700">{URGENCY_LABEL[ins.urgency]}</span>
          </div>
        </div>
      </section>

      <Block n={8} title="Рекомендуемые действия" hint="Добавьте нужные шаги в план — они появятся в разделе «Решения»">
        <ActionsBlock actions={ins.actions} added={added} onAdd={onAdd} />
      </Block>

      <Block n={9} title="Что отслеживать дальше">
        {ins.indicators.length === 0 ? <p className="text-sm text-ink-500">—</p> : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {ins.indicators.map((x) => (
              <li key={x} className="flex gap-2 text-sm text-ink-700"><Eye size={14} className="mt-0.5 shrink-0 text-ink-400" /> {x}</li>
            ))}
          </ul>
        )}
      </Block>

      <Block n={10} title="Обоснование" hint="Источники, допущения и пробелы в данных">
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <div className="label">Источники</div>
            <ul className="space-y-1.5 text-sm">
              <li>
                {ev.url ? <a href={ev.url} target="_blank" rel="noreferrer" className="text-ink-900 underline decoration-ink-300 hover:decoration-ink-900">{ev.source}</a>
                  : <span>{ev.source} <span className="text-xs text-ink-400">(синтетика, без ссылки)</span></span>}
                <span className="text-xs text-ink-400"> · {formatDate(ev.published_at)}</span>
              </li>
              {ev.related.map((r) => (
                <li key={r.id}>
                  {r.url ? <a href={r.url} target="_blank" rel="noreferrer" className="underline decoration-ink-300">{r.source}</a> : r.source}
                  <span className="text-xs text-ink-400"> · {r.title}</span>
                </li>
              ))}
            </ul>
            <div className="label mt-4">Уверенность в выводе</div>
            <p className="text-sm"><span className="font-semibold">{ins.confidence}/100</span>
              <span className="text-ink-500"> — {ins.confidence >= 70 ? "высокая" : ins.confidence >= 45 ? "средняя" : "низкая, требуется проверка"}</span></p>
          </div>
          <div className="space-y-4">
            <div>
              <div className="label">Допущения анализа</div>
              <ul className="list-disc space-y-1 pl-4 text-sm text-ink-700">
                {ins.assumptions.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
            {ins.data_gaps.length > 0 && (
              <div>
                <div className="label">Чего не хватает</div>
                <ul className="list-disc space-y-1 pl-4 text-sm text-amber-800">
                  {ins.data_gaps.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      </Block>
    </>
  );
}

function ComparePanel({ eventId }: { eventId: string }) {
  const { profileId, setProfileId, bumpData, dataVersion } = useApp();
  const { data, loading, error } = useLoad(() => api.compare(eventId), [eventId, dataVersion]);
  return (
    <section className="card overflow-hidden">
      <div className="px-5 pt-5">
        <h2 className="section-title">Та же новость для других компаний</h2>
        <p className="mt-0.5 text-xs text-ink-500">Оценка зависит от профиля: отрасли, регионов, контрагентов и стратегии</p>
      </div>
      {loading && <Loading text="Считаем оценки…" />}
      {error && <div className="p-5"><ErrorBox error={error} /></div>}
      {data && (
        <div className="mt-3 divide-y divide-ink-100">
          {data.map((r) => (
            <div key={r.profile_id} className={`flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center ${r.profile_id === profileId ? "bg-ink-50" : ""}`}>
              <PriorityScore value={r.priority} level={r.priority_level} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{r.profile_name}</span>
                  <ImpactBadge type={r.impact_type} />
                  {r.profile_id === profileId && <span className="text-xs text-ink-500">текущий профиль</span>}
                </div>
                <p className="mt-0.5 text-sm text-ink-700">{r.summary_line}</p>
                <p className="mt-0.5 text-xs text-ink-500">
                  Релевантность {r.relevance}{r.top_factors.length > 0 && " · " + r.top_factors.map((f) => `${f.label} +${f.points}`).join(", ")}
                </p>
              </div>
              {r.profile_id !== profileId && (
                <button className="btn-secondary shrink-0 !py-1.5" onClick={() => { setProfileId(r.profile_id); bumpData(); }}>
                  Открыть для этой компании
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function EventPage() {
  const { id = "" } = useParams();
  const { profileId, profile, dataVersion, toast } = useApp();
  const { data, setData, loading, error, reload } = useLoad(() => api.event(profileId, id), [profileId, id, dataVersion]);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<ActionDraft | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [showRules, setShowRules] = useState(false);
  const [showText, setShowText] = useState(false);

  if (loading && !data) return <Loading text="Загружаем событие и считаем аналитику…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const ev = data;
  const ins = showRules ? ev.rules_insight : ev.insight;
  const inPlan = new Set([...(ev.linked_action_titles ?? []), ...added]);

  const toggleFav = async () => {
    try {
      const r = await api.toggleFavorite(profileId, ev.id);
      setData({ ...ev, favorite: r.favorite });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const openDraft = (a?: SuggestedAction) => {
    setDraft({
      title: a?.title || "",
      description: a?.description || "",
      priority: a?.priority || (ev.priority_level === "critical" || ev.priority_level === "high" ? "high" : "medium"),
      due_date: a?.due_date || null,
      owner: a?.owner || "",
      comment: "",
    });
  };

  const saveDraft = async (d: ActionDraft) => {
    await api.createAction({ ...d, profile_id: profileId, event_id: ev.id });
    setAdded((prev) => new Set(prev).add(d.title));
    setData({ ...ev, linked_actions: ev.linked_actions + 1 });
    setDraft(null);
    toast("Действие добавлено в план");
  };

  const runLlm = async () => {
    setLlmBusy(true);
    setLlmError(null);
    try {
      const res = await api.runLlm(profileId, ev.id);
      setData({ ...ev, insight: res.insight, llm: { ...ev.llm, cached: true, stale: false } });
      setShowRules(false);
      toast("Получен углублённый анализ LLM");
    } catch (e: any) {
      setLlmError(e.message);
    } finally {
      setLlmBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Link to="/feed" className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-ink-900">
        <ArrowLeft size={15} /> К ленте событий
      </Link>

      {ev.suspicious && (
        <div className="flex gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <ShieldAlert size={18} className="mt-0.5 shrink-0" />
          <p>В тексте публикации есть инструкции, адресованные ИИ-системам (например, «присвой максимальный приоритет»).
            Они не выполнялись: текст обрабатывается как данные, а уверенность в выводе снижена. Проверьте первоисточник.</p>
        </div>
      )}

      <header className="card p-5">
        <div className="flex flex-wrap items-center gap-2">
          {ev.is_demo && <DemoBadge />}
          <span className="rounded-md bg-ink-100 px-2 py-0.5 text-xs font-medium text-ink-700">{ev.category_label}</span>
          <ImpactBadge type={ev.impact_type} />
          <UrgencyBadge level={ev.urgency_level} />
          <FactBadge status={ev.fact_status} />
        </div>
        <h1 className="mt-3 text-xl font-semibold leading-snug sm:text-2xl">{ev.title}</h1>
        {ev.title_original && ev.title_original !== ev.title && (
          <p className="mt-1 text-sm text-ink-500">Заголовок оригинала: «{ev.title_original}»</p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-500">
          <span>{ev.source}</span>
          <span title={ev.time_approx ? "Точное время публикации неизвестно" : undefined}>
            {ev.time_approx ? formatDate(ev.published_at, false) : formatDate(ev.published_at)}
          </span>
          {ev.url ? (
            <a href={ev.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-ink-700 hover:underline">
              <ExternalLink size={14} /> Оригинал публикации
            </a>
          ) : (
            <span className="text-ink-400">Синтетическое событие: оригинала нет</span>
          )}
          {ev.related.length > 0 && <span>Объединено публикаций: {ev.related.length + 1}</span>}
        </div>
        <div className="mt-4 rounded-lg bg-ink-50 px-4 py-3">
          <div className="text-xs font-medium uppercase tracking-wide text-ink-500">Главное для {profile?.name}</div>
          <p className="mt-1 font-medium">{ev.insight.summary_line}</p>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-primary" onClick={() => openDraft()}><Plus size={15} /> Создать действие</button>
          <button className={`btn-secondary ${ev.favorite ? "!text-amber-600" : ""}`} onClick={toggleFav}>
            <Star size={15} fill={ev.favorite ? "currentColor" : "none"} /> {ev.favorite ? "В избранном" : "В избранное"}
          </button>
          {ev.linked_actions > 0 && (
            <Link to="/decisions" className="btn-ghost">Связанных действий: {ev.linked_actions}</Link>
          )}
          <button className="btn-ghost" onClick={() => setShowText((s) => !s)}>
            <FileText size={15} /> {showText ? "Скрыть текст" : ev.paraphrase ? "Пересказ публикации" : "Текст публикации"}
          </button>
        </div>
        {showText && (
          <div className="mt-4 whitespace-pre-line rounded-lg border border-ink-100 p-4 text-sm leading-relaxed text-ink-700">
            {ev.paraphrase && (
              <p className="mb-2 text-xs text-ink-500">
                Краткий пересказ фактов, подготовленный командой. Полный текст — по ссылке на оригинал.
              </p>
            )}
            {ev.summary && <p className="mb-2 font-medium">{ev.summary}</p>}
            {ev.body || "Полного текста нет — доступен только анонс."}
          </div>
        )}
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <div className="card overflow-hidden">
            <div className="flex flex-wrap items-center gap-3 border-b border-ink-100 bg-ink-50/60 px-5 py-3">
              <Bot size={16} className="text-ink-500" />
              <div className="min-w-0 flex-1 text-sm">
                {ins.engine === "llm" ? (
                  <span><b>Анализ LLM</b> <span className="text-ink-500">({ins.model}) · факты сверены с текстом, баллы считает система</span></span>
                ) : (
                  <span><b>Анализ на правилах</b> <span className="text-ink-500">· каналы влияния по профилю, без языковой модели</span></span>
                )}
              </div>
              {ev.llm.cached && !ev.llm.stale && (
                <button className="btn-ghost !py-1 text-xs" onClick={() => setShowRules((s) => !s)}>
                  {showRules ? "Показать анализ LLM" : "Показать вариант правил"}
                </button>
              )}
              <button className="btn-secondary !py-1.5 text-xs" onClick={runLlm} disabled={!ev.llm.enabled || llmBusy}
                title={ev.llm.enabled ? "Запросить разбор у языковой модели" : "LLM не подключён: нужен ANTHROPIC_API_KEY в .env"}>
                {llmBusy ? "Анализируем…" : ev.llm.cached ? "Обновить анализ LLM" : "Углублённый анализ LLM"}
              </button>
            </div>
            {!ev.llm.enabled && (
              <div className="flex gap-2 border-b border-ink-100 px-5 py-2 text-xs text-ink-500">
                <Info size={14} className="shrink-0" /> LLM не подключён — работает базовый движок правил. Это не имитация LLM: выводы собраны из шаблонов по найденным связям с профилем.
              </div>
            )}
            {ev.llm.stale && (
              <div className="border-b border-ink-100 px-5 py-2 text-xs text-amber-800">
                Профиль компании изменился после последнего анализа LLM — показан анализ правил, LLM можно запросить заново.
              </div>
            )}
            {llmError && <div className="border-b border-red-100 bg-red-50 px-5 py-2 text-sm text-red-800">{llmError}</div>}
            <Analysis ins={ins} ev={ev} added={inPlan} onAdd={openDraft} />
          </div>
          <ComparePanel eventId={ev.id} />
        </div>
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <ScorePanel score={ev.score} profileName={profile?.name} />
        </aside>
      </div>

      {draft && (
        <Modal title="Новое действие" onClose={() => setDraft(null)}>
          <p className="mb-4 rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-500">Событие: {ev.title}</p>
          <ActionForm initial={draft} submitLabel="Добавить в план" onSubmit={saveDraft} onCancel={() => setDraft(null)} />
        </Modal>
      )}
    </div>
  );
}
