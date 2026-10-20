import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, ExternalLink, Info, RefreshCw, Send, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api } from "../api";
import type { AgentRun, AgentSource, AgentStep, Claim, ClaimKind } from "../types";

// разделение, которого требует кейс: факты из новости, позиция банка, данные о клиенте и выводы модели
const KIND: Record<ClaimKind, { label: string; cls: string }> = {
  fact: { label: "Факт из новости", cls: "bg-sky-50 text-sky-800 ring-sky-200" },
  bank: { label: "Позиция банка", cls: "bg-rose-50 text-rose-800 ring-rose-200" },
  client: { label: "Данные о компании", cls: "bg-violet-50 text-violet-800 ring-violet-200" },
  ai: { label: "Вывод AI", cls: "bg-amber-50 text-amber-900 ring-amber-200" },
};

const STEP_LABEL: Record<AgentStep["kind"], string> = {
  plan: "План",
  tool: "Инструмент",
  check: "Самопроверка",
  synthesis: "Ответ",
};

function KindBadge({ kind }: { kind: ClaimKind }) {
  const k = KIND[kind];
  return <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${k.cls}`}>{k.label}</span>;
}

function Refs({ ids, index }: { ids: string[]; index: Map<string, number> }) {
  const nums = ids.map((id) => index.get(id)).filter((n): n is number => n !== undefined);
  if (!nums.length) return null;
  return (
    <span className="ml-1 whitespace-nowrap text-[11px] text-ink-400">
      {nums.map((n) => <a key={n} href={`#agent-src-${n}`} className="hover:text-ink-900">[{n}]</a>)}
    </span>
  );
}

function Claims({ items, index, empty }: { items: Claim[]; index: Map<string, number>; empty?: string }) {
  if (!items.length) return <p className="text-sm text-ink-400">{empty || "Нет данных"}</p>;
  return (
    <ul className="space-y-2">
      {items.map((c, i) => (
        <li key={i} className="flex flex-col gap-1 text-sm sm:flex-row sm:items-start sm:gap-2">
          <KindBadge kind={c.kind} />
          <span className="text-ink-800">
            {c.text}<Refs ids={c.sources} index={index} />
            {c.confirmed === false && <span className="ml-1.5 whitespace-nowrap rounded bg-amber-50 px-1 text-[11px] text-amber-800">не подтверждено</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Block({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="border-t border-ink-100 px-5 py-4 first:border-t-0">
      <h3 className="mb-2.5 flex items-center gap-2 text-sm font-semibold text-ink-900">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-ink-900 text-[11px] text-white">{n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function SourceRow({ s, n }: { s: AgentSource; n: number }) {
  const type = { news: "Новость", bank: "Аналитика банка", client: "Данные о компании", rules: "Правила сервиса", market: "Рынок" }[s.type];
  return (
    <li id={`agent-src-${n}`} className="flex gap-2 text-xs">
      <span className="w-6 shrink-0 text-ink-400">[{n}]</span>
      <span className="min-w-0">
        <span className="text-ink-500">{type}: </span>
        {s.url ? (
          <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-ink-800 hover:underline">
            {s.title} <ExternalLink size={11} />
          </a>
        ) : <span className="text-ink-800">{s.title}</span>}
        {s.detail && <span className="text-ink-500"> · {s.detail}</span>}
      </span>
    </li>
  );
}

function Trace({ steps, ms }: { steps: AgentStep[]; ms: number }) {
  return (
    <ol className="space-y-1.5 px-5 pb-4 text-xs">
      {steps.map((s) => (
        <li key={s.n} className="flex gap-2">
          <span className="w-5 shrink-0 text-right tabular-nums text-ink-400">{s.n}.</span>
          <span className="min-w-0">
            <span className={`mr-1.5 rounded px-1 py-0.5 ${s.ok === false ? "bg-red-50 text-red-700" : "bg-ink-100 text-ink-600"}`}>
              {STEP_LABEL[s.kind]}{s.tool ? ` · ${s.tool}` : ""}
            </span>
            <span className="text-ink-800">{s.why || s.title}</span>
            {s.args && Object.keys(s.args).length > 0 && (
              <span className="text-ink-400"> ({Object.entries(s.args).map(([k, v]) => `${k}: «${v}»`).join(", ")})</span>
            )}
            {s.result && <span className="text-ink-500"> → {s.result}</span>}
            {s.kind === "check" && s.gaps && (
              <span className="text-ink-500"> → {s.gaps.length ? `не хватает: ${s.gaps.join("; ")}` : "данных достаточно"}
                {s.extra?.length ? `; доп. шаги: ${s.extra.join(", ")}` : ""}</span>
            )}
            {s.issues && s.issues.length > 0 && <span className="text-amber-700"> · противоречия: {s.issues.join(" ")}</span>}
            {s.plan && <span className="text-ink-500"> → {s.plan.map((p) => p.tool).join(" → ")}</span>}
            {s.model && <span className="text-ink-400"> · {s.model}{s.fallback_from ? ` (запасная вместо ${s.fallback_from})` : ""}</span>}
            {s.prompt && <span className="text-ink-400"> · промпт {s.prompt}</span>}
            {s.tokens ? <span className="text-ink-400"> · {s.tokens} ток., {(s.cost_rub ?? 0).toFixed(3)} ₽{s.cached ? ", из кэша" : ""}</span> : null}
            {s.ms !== undefined && s.ms > 0 && <span className="text-ink-400"> · {s.ms} мс</span>}
          </span>
        </li>
      ))}
      <li className="pl-7 text-ink-400">Всего: {ms} мс. Журнал запусков хранится в таблице agent_runs.</li>
    </ol>
  );
}

// «Инсайт для руководителя»: агент сам планирует шаги, вызывает инструменты и отвечает на 6 вопросов кейса
export default function AgentPanel({ profileId, eventId, llmEnabled }: { profileId: string; eventId: string; llmEnabled: boolean }) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [showTrace, setShowTrace] = useState(false);

  const go = async (q = "", refresh = false) => {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.agentInsight(profileId, eventId, q, refresh));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // без LLM запуск дешёвый — готовим инсайт сразу; с моделью ждём кнопку, чтобы не тратить лимит токенов
  useEffect(() => {
    setRun(null);
    if (!llmEnabled) go();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, eventId, llmEnabled]);

  const ask = (e: FormEvent) => {
    e.preventDefault();
    if (question.trim()) go(question.trim(), true);
  };

  const r = run?.result;
  const a = r?.answers;
  const index = new Map((a?.basis.sources || []).map((s, i) => [s.id, i + 1]));
  const tools = run ? run.trace.filter((s) => s.kind === "tool").length : 0;

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-ink-100 bg-ink-50/60 px-5 py-3">
        <Sparkles size={16} className="text-rose-600" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Инсайт для руководителя</div>
          <div className="text-xs text-ink-500">
            {run
              ? `Агент: ${tools} вызовов инструментов, ${r!.mode === "llm" ? `модели ${(r!.llm?.models || [r!.model]).join(", ")}${r!.llm?.mock ? " (мок)" : ""}` : "без LLM, на правилах и поиске"}`
                + (run.cached ? " · сохранённый запуск" : "")
              : "Агент планирует, какие данные нужны, вызывает инструменты, проверяет полноту и отвечает на 6 вопросов"}
          </div>
        </div>
        {run ? (
          <button className="btn-ghost !py-1 text-xs" onClick={() => go(r?.question || "", true)} disabled={busy}>
            <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> Перезапустить
          </button>
        ) : (
          <button className="btn-primary !py-1.5 text-xs" onClick={() => go()} disabled={busy}>
            {busy ? "Агент работает…" : "Подготовить инсайт"}
          </button>
        )}
      </div>

      {error && <div className="border-b border-red-100 bg-red-50 px-5 py-2 text-sm text-red-800">{error}</div>}
      {r?.llm?.degraded && (
        <div className="flex gap-2 border-b border-amber-100 bg-amber-50 px-5 py-2 text-xs text-amber-900">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {r.llm.degraded.reason === "budget"
            ? "Дневной лимит бюджета LLM исчерпан — ответ собран правилами и своими моделями без языковой модели."
            : "Модели недоступны (ошибка или таймаут у основной и запасной) — ответ собран правилами."}
        </div>
      )}
      {r?.llm && !r.llm.degraded && (r.llm.mock || r.llm.cached) && (
        <div className="flex gap-2 border-b border-ink-100 bg-ink-50 px-5 py-2 text-xs text-ink-600">
          <Info size={14} className="mt-0.5 shrink-0" />
          {r.llm.mock ? "Мок-режим шлюза: формулировки построены из собранных данных без языковой модели (ключа шлюза пока нет). " : ""}
          {r.llm.cached ? "Ответ модели взят из кэша — бюджет не тратился." : ""}
        </div>
      )}
      {busy && !run && <div className="px-5 py-6 text-sm text-ink-500">Агент собирает данные: событие, профиль, данные банка, аналитика…</div>}

      {r && a && (
        <div className={busy ? "opacity-60" : ""}>
          <div className="border-b border-ink-100 px-5 py-3">
            <p className="font-medium text-ink-900">{r.summary}</p>
            {r.question && <p className="mt-1 text-xs text-ink-500">Вопрос: {r.question}</p>}
            <div className="mt-2 flex flex-wrap gap-1.5">{(Object.keys(KIND) as ClaimKind[]).map((k) => <KindBadge key={k} kind={k} />)}</div>
          </div>

          {a.question && (
            <section className="border-b border-ink-100 bg-sky-50/40 px-5 py-4">
              <h3 className="mb-2 text-sm font-semibold text-ink-900">Ответ на вопрос: «{a.question.text}»</h3>
              <Claims items={a.question.items} index={index} empty="Прямого ответа в собранных данных нет" />
              {a.question.note && <p className="mt-2 text-xs text-ink-500">{a.question.note}</p>}
            </section>
          )}

          <Block n={1} title="Что произошло?">
            <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs">
              <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 ${a.event.confirmation.status === "single" ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-800"}`}>
                {a.event.confirmation.status === "single" ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
                {a.event.confirmation.label}
              </span>
              {a.event.participants.length > 0 && <span className="text-ink-600"><b className="font-medium">Участники:</b> {a.event.participants.join(", ")}</span>}
            </div>
            <Claims items={a.what_happened} index={index} empty="В тексте новости нет проверяемых фактов" />
            {a.event.dates.length > 0 && <p className="mt-2 text-xs text-ink-600"><b className="font-medium">Сроки и даты:</b> {a.event.dates.join(" · ")}</p>}
          </Block>
          <Block n={2} title="Почему это важно для компании?">
            <Claims items={a.why_important} index={index} />
          </Block>
          <Block n={3} title="Какие последствия: риски и возможности">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-1.5 text-xs font-medium text-rose-700">Риски</div>
                <Claims items={a.consequences.risks} index={index} empty="Рисков не выявлено" />
              </div>
              <div>
                <div className="mb-1.5 text-xs font-medium text-emerald-700">Возможности</div>
                <Claims items={a.consequences.opportunities} index={index} empty="Возможностей не выявлено" />
              </div>
            </div>
            {a.consequences.bank_adjusted.length > 0 && (
              <div className="mt-3">
                <div className="mb-1.5 text-xs font-medium text-rose-700">С учётом аналитики банка</div>
                <Claims items={a.consequences.bank_adjusted} index={index} />
              </div>
            )}
            {a.consequences.horizon && <p className="mt-2 text-xs text-ink-500">Горизонт влияния: {a.consequences.horizon}</p>}
          </Block>
          <Block n={4} title="Какие действия актуальны?">
            {a.actions.length ? (
              <ul className="space-y-3">
                {a.actions.map((x, i) => (
                  <li key={i} className="text-sm">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-2">
                      <KindBadge kind={x.kind} />
                      <span className="font-medium text-ink-900">{x.title}
                        {x.owner && <span className="font-normal text-ink-500"> · {x.owner}{x.due_days ? `, ${x.due_days} дн.` : ""}</span>}
                      </span>
                    </div>
                    <div className="mt-1 space-y-0.5 text-xs text-ink-600 sm:pl-[6.5rem]">
                      {x.why && <p><b className="font-medium">Почему:</b> {x.why}</p>}
                      {x.if_done && <p><b className="font-medium">Если сделать:</b> {x.if_done}</p>}
                      {x.if_ignored && <p><b className="font-medium">Если не реагировать:</b> {x.if_ignored}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-ink-400">Действий не требуется — достаточно мониторинга</p>}
            {a.follow_up.scenarios.length > 0 && (
              <div className="mt-4">
                <div className="mb-1.5 text-xs font-medium text-ink-700">Сценарии развития</div>
                <div className="grid gap-2 md:grid-cols-2">
                  {a.follow_up.scenarios.map((sc, i) => (
                    <div key={i} className={`rounded-lg border px-3 py-2 text-xs ${sc.bank_view ? "border-rose-200 bg-rose-50/40" : "border-ink-100"}`}>
                      <div className="flex items-center gap-1.5 font-medium text-ink-900"><KindBadge kind={sc.kind} /> {sc.title}</div>
                      <p className="mt-1 text-ink-700">{sc.text}<Refs ids={sc.sources} index={index} /></p>
                      {sc.bank_view && <p className="mt-1 font-medium text-rose-700">{sc.bank_view}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {a.follow_up.questions.length > 0 && (
              <div className="mt-4 text-xs text-ink-700">
                <div className="mb-1 font-medium">Вопросы для дополнительного анализа</div>
                <ul className="list-disc space-y-0.5 pl-4">{a.follow_up.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
              </div>
            )}
            {a.follow_up.indicators.length > 0 && (
              <p className="mt-3 text-xs text-ink-600"><b className="font-medium">Что отслеживать:</b> {a.follow_up.indicators.join(" · ")}</p>
            )}
          </Block>
          <Block n={5} title="Как это оценивает банк?">
            {a.bank_view.found && (
              <div className="mb-2 flex flex-wrap gap-1.5 text-xs">
                <span className={`rounded px-1.5 py-0.5 ${a.bank_view.agreement === "conflict" ? "bg-amber-50 text-amber-800" : a.bank_view.agreement === "agree" ? "bg-emerald-50 text-emerald-800" : "bg-ink-100 text-ink-600"}`}>
                  {a.bank_view.agreement === "conflict" ? "Расходится с новостью" : a.bank_view.agreement === "agree" ? "Совпадает с направлением новости" : "Дополняет картину"}
                </span>
                {a.bank_view.topics.map((t) => <span key={t} className="rounded bg-ink-100 px-1.5 py-0.5 text-ink-600">{t}</span>)}
              </div>
            )}
            <Claims items={a.bank_view.items} index={index} empty={a.bank_view.note || "Нет позиции банка"} />
            {!a.bank_view.found && (
              <p className="mt-2 flex gap-1.5 text-xs text-ink-500">
                <Info size={13} className="mt-0.5 shrink-0" /> Агент искал дважды (по теме события и по отрасли). Позиция банка
                не придумывается: появится, когда аналитические материалы банка будут загружены в BANK_DOCS_DIR.
              </p>
            )}
          </Block>
          <Block n={6} title="На чём основан вывод?">
            {a.basis.client_features.length > 0 && (
              <p className="mb-2 text-xs text-ink-600"><b className="font-medium">Особенности компании:</b> {a.basis.client_features.join(" · ")}</p>
            )}
            {a.basis.market && (
              <p className="mb-2 text-xs text-ink-600"><b className="font-medium">Рынок:</b> {a.basis.market.ticker} {a.basis.market.ar}% к индексу за {a.basis.market.horizon} дн.</p>
            )}
            <ol className="space-y-1">{a.basis.sources.map((s, i) => <SourceRow key={s.id} s={s} n={i + 1} />)}</ol>
            <div className="mt-3 space-y-1 text-xs">
              <p className="text-ink-600">
                <b className="font-medium">Проверка обоснованности:</b> утверждений {r.checks.grounding.claims}, без источника
                отброшено {r.checks.grounding.dropped}{r.checks.grounding.llm_dropped ? `, выводов модели без опоры на данные — ${r.checks.grounding.llm_dropped}` : ""}.
              </p>
              {r.checks.consistency.length > 0 ? (
                <div className="rounded-lg bg-amber-50 px-3 py-2 text-amber-900">
                  <b className="font-medium">Противоречия в данных (уверенность снижена):</b>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">{r.checks.consistency.map((x, i) => <li key={i}>{x.text}<Refs ids={x.sources} index={index} /></li>)}</ul>
                </div>
              ) : <p className="text-ink-600"><b className="font-medium">Проверка на противоречия:</b> расхождений между источниками не найдено.</p>}
            </div>
            {r.data_gaps.length > 0 && (
              <div className="mt-3 rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-600">
                <b className="font-medium">Ограничения и чего не хватило агенту:</b>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">{r.data_gaps.map((g, i) => <li key={i}>{g[0].toUpperCase() + g.slice(1)}</li>)}</ul>
              </div>
            )}
          </Block>

          <form onSubmit={ask} className="flex gap-2 border-t border-ink-100 px-5 py-3">
            <input className="input flex-1 !py-1.5 text-sm" placeholder="Уточнить у агента: например, «что это значит для наших кредитов?»"
              value={question} maxLength={500} onChange={(e) => setQuestion(e.target.value)} />
            <button className="btn-secondary !py-1.5 text-sm" disabled={busy || !question.trim()}><Send size={14} /> Спросить</button>
          </form>

          <button className="flex w-full items-center gap-1.5 border-t border-ink-100 px-5 py-2.5 text-left text-xs text-ink-500 hover:text-ink-900"
            onClick={() => setShowTrace((s) => !s)}>
            {showTrace ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Как агент пришёл к выводу: {run!.trace.length} шагов
          </button>
          {showTrace && <Trace steps={run!.trace} ms={run!.ms} />}
        </div>
      )}
    </div>
  );
}
