import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, ExternalLink, FileText, Info, RefreshCw, Send, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api } from "../api";
import { useApp } from "../context";
import type { AgentResult, AgentRun, AgentSource, AgentStep, Claim, ClaimKind } from "../types";

// разделение, которого требует кейс: факт, позиция банка, вывод ИИ (и данные о компании, на которых он основан)
const KIND: Record<ClaimKind, { label: string; cls: string; hint: string }> = {
  fact: { label: "Факт", cls: "bg-sky-50 text-sky-800 ring-sky-200", hint: "из текста новости, со ссылкой на издание" },
  bank: { label: "Позиция банка", cls: "bg-rose-50 text-rose-800 ring-rose-200", hint: "цитата аналитики Альфа-Банка со страницей материала" },
  client: { label: "Данные о компании", cls: "bg-violet-50 text-violet-800 ring-violet-200", hint: "профиль и данные банка о клиенте" },
  ai: { label: "Вывод ИИ", cls: "bg-amber-50 text-amber-900 ring-amber-200", hint: "вывод модели, правил и своих ML-моделей" },
};
const DATA_LABEL: Record<string, string> = { public: "публичные", bank_internal: "внутренние банка", client_confidential: "данные клиента" };

const STEP_LABEL: Record<AgentStep["kind"], string> = {
  plan: "План",
  tool: "Инструмент",
  check: "Самопроверка",
  synthesis: "Ответ",
};

function KindBadge({ kind }: { kind: ClaimKind }) {
  const k = KIND[kind];
  return <span title={k.hint} className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${k.cls}`}>{k.label}</span>;
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
            {c.for_role && <span className="mr-1.5 rounded bg-ink-900 px-1 text-[10px] font-medium text-white">для вас</span>}
            {c.text}<Refs ids={c.sources} index={index} />
            {c.confirmed === false && <span className="ml-1.5 whitespace-nowrap rounded bg-amber-50 px-1 text-[11px] text-amber-800">не подтверждено</span>}
            {c.link && (
              <a href={c.link.url} target="_blank" rel="noreferrer" className="ml-1.5 inline-flex items-center gap-0.5 whitespace-nowrap text-[11px] text-rose-700 hover:underline">
                <FileText size={11} /> {c.link.title.slice(0, 40)}{c.link.title.length > 40 ? "…" : ""}, стр. {c.link.page}{c.link.date ? `, ${c.link.date}` : ""}
              </a>
            )}
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
  const type = { news: "Новость", bank: "Аналитика банка", client: "Данные о компании", rules: "Правила сервиса", market: "Рынок", model: "Своя ML-модель" }[s.type];
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
            {s.plan_json && <span className="block text-ink-500">Цель: {s.plan_json.goal}. Источники: {s.plan_json.sources.join(", ")}.</span>}
            {s.rights && <span className="ml-1 rounded bg-ink-50 px-1 text-[10px] text-ink-500" title="права инструмента">{s.rights.access === "read" ? "чтение" : s.rights.access}, {DATA_LABEL[s.rights.data] || s.rights.data}</span>}
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

function ContradictionCard({ c }: { c: NonNullable<AgentResult["contradictions"]>[number] }) {
  return (
    <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-xs">
      <div className="mb-2 flex items-center gap-1.5 font-medium text-amber-900"><AlertTriangle size={13} /> Новость и аналитика банка расходятся: {c.topic}</div>
      <div className="grid gap-2 md:grid-cols-2">
        <div className="rounded bg-white p-2">
          <KindBadge kind="fact" />
          <p className="mt-1 text-ink-800">{c.news.text}</p>
          {c.news.url && <a href={c.news.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-ink-500 hover:underline"><ExternalLink size={11} /> первоисточник</a>}
        </div>
        <div className="rounded bg-white p-2">
          <KindBadge kind="bank" />
          <p className="mt-1 text-ink-800">{c.bank.text}</p>
          {c.bank.url && <a href={c.bank.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-rose-700 hover:underline"><FileText size={11} /> материал банка{c.bank.date ? ` от ${c.bank.date}` : ""}</a>}
        </div>
      </div>
      <p className="mt-2 text-amber-900">{c.note}</p>
    </div>
  );
}

function Features({ r }: { r: AgentResult }) {
  const model = (r.features || []).filter((f) => f.source === "case_model" && f.contribution !== null);
  const rules = (r.features || []).filter((f) => f.source === "rules");
  if (!model.length && !rules.length) return null;
  const max = Math.max(0.001, ...model.map((f) => Math.abs(f.contribution || 0)));
  return (
    <div className="mb-3 text-xs">
      <div className="mb-1 font-medium text-ink-700">Признаки компании, повлиявшие на вывод</div>
      {model.length > 0 && (
        <ul className="mb-2 space-y-1">
          {model.map((f) => (
            <li key={f.label}>
              <div className="flex justify-between gap-2"><span className="text-ink-700">{f.label}</span>
                <span className={`tabular-nums ${(f.contribution || 0) > 0 ? "text-emerald-700" : "text-rose-700"}`}>{(f.contribution || 0) > 0 ? "+" : ""}{(f.contribution || 0).toFixed(2)}</span></div>
              <div className="mt-0.5 h-1 rounded-full bg-ink-100"><div className={`h-1 rounded-full ${(f.contribution || 0) > 0 ? "bg-emerald-500" : "bg-rose-500"}`} style={{ width: `${(Math.abs(f.contribution || 0) / max) * 100}%` }} /></div>
            </li>
          ))}
          <li className="text-ink-400">Вклад своей модели (не LLM) по данным клиента; модель черновая, пока нет ручной разметки.</li>
        </ul>
      )}
      {rules.length > 0 && <p className="text-ink-600">Совпадения с профилем: {rules.map((f) => f.label).join(" · ")}</p>}
    </div>
  );
}

// «Инсайт для руководителя»: агент сам планирует шаги, вызывает инструменты и отвечает на 6 вопросов кейса
export default function AgentPanel({ profileId, eventId, llmEnabled, llmLabel }:
  { profileId: string; eventId: string; llmEnabled: boolean; llmLabel: string }) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [showTrace, setShowTrace] = useState(false);
  const { role } = useApp();

  const go = async (q = "", refresh = false) => {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.agentInsight(profileId, eventId, q, refresh, role));
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
  }, [profileId, eventId, llmEnabled, role]);

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
              ? `Агент: ${tools} вызовов инструментов, ${r!.mode === "llm" ? `модели ${(r!.llm?.models || [r!.model]).join(", ")}${r!.llm?.mock ? " (тестовый режим)" : ""}` : "без LLM, на правилах и поиске"}`
                + (r!.from_cache ? " · ответ из кэша" : run.cached ? " · сохранённый запуск" : "")
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
      {r?.from_cache && (
        <div className="flex gap-2 border-b border-sky-100 bg-sky-50 px-5 py-2 text-xs text-sky-900">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            <b>Ответ из кэша</b>, получен ранее моделью {r.from_cache.model || "—"}
            {r.from_cache.obtained_at ? `, ${new Date(r.from_cache.obtained_at).toLocaleDateString("ru-RU")}` : ""}
            {r.from_cache.prompts.length ? ` (промпты ${r.from_cache.prompts.join(", ")})` : ""}. Сейчас: {llmLabel.toLowerCase()} —
            перезапуск и новые события разбираются правилами и своими ML-моделями.
          </span>
        </div>
      )}
      {r && r.mode === "rules" && !r.llm && !r.from_cache && (
        <div className="flex gap-2 border-b border-ink-100 bg-ink-50 px-5 py-2 text-xs text-ink-600">
          <Info size={14} className="mt-0.5 shrink-0" />
          {llmLabel}: разбор собран правилами, своими ML-моделями и поиском по источникам — это не ответ LLM.
        </div>
      )}
      {r?.llm?.degraded && (
        <div className="flex gap-2 border-b border-amber-100 bg-amber-50 px-5 py-2 text-xs text-amber-900">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          {r.llm.degraded.reason === "budget"
            ? "Дневной лимит исчерпан: ответы из правил и кэша. Этот разбор собран правилами и своими моделями."
            : "Модели недоступны (ошибка или таймаут у основной и запасной) — ответ собран правилами."}
        </div>
      )}
      {r?.llm && !r.llm.degraded && (r.llm.mock || r.llm.cached) && (
        <div className="flex gap-2 border-b border-ink-100 bg-ink-50 px-5 py-2 text-xs text-ink-600">
          <Info size={14} className="mt-0.5 shrink-0" />
          {r.llm.mock ? "Тестовый режим (ответы-заглушки): формулировки построены из собранных данных без настоящей языковой модели. " : ""}
          {r.llm.cached ? "Ответ модели взят из кэша — бюджет не тратился." : ""}
        </div>
      )}
      {busy && !run && <div className="px-5 py-6 text-sm text-ink-500">Агент собирает данные: событие, профиль, данные банка, аналитика…</div>}

      {r && a && (
        <div className={busy ? "opacity-60" : ""}>
          <div className="border-b border-ink-100 px-5 py-3">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-2">
              <KindBadge kind="ai" />
              <p className="font-medium text-ink-900">{r.summary}<Refs ids={r.ai_conclusion?.sources || []} index={index} /></p>
            </div>
            {r.ai_conclusion && (
              <p className="mt-1 text-xs text-ink-500">
                {r.ai_conclusion.model ? `Сформулировала модель ${r.ai_conclusion.model}${r.llm?.mock ? " (тестовый режим)" : ""}, промпт ${r.ai_conclusion.prompt}` : `Без языковой модели: ${r.ai_conclusion.engine}`}
              </p>
            )}
            {r.question && <p className="mt-1 text-xs text-ink-500">Вопрос: {r.question}</p>}
            {r.role && <p className="mt-1.5 rounded bg-ink-50 px-2 py-1 text-xs text-ink-700"><b className="font-medium">{r.role.label}:</b> {r.role.note}</p>}
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
                      <span className="font-medium text-ink-900">
                        {x.for_role && <span className="mr-1.5 rounded bg-ink-900 px-1 text-[10px] font-medium text-white">для вас</span>}
                        {x.title}
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
            {(r.contradictions || []).map((c, i) => <ContradictionCard key={i} c={c} />)}
            {!a.bank_view.found && (
              <p className="mt-2 flex gap-1.5 text-xs text-ink-500">
                <Info size={13} className="mt-0.5 shrink-0" /> Агент искал дважды (по теме события и по отрасли). Позиция банка
                не придумывается: появится, когда аналитические материалы банка будут загружены в BANK_DOCS_DIR.
              </p>
            )}
          </Block>
          <Block n={6} title="На чём основан вывод?">
            <Features r={r} />
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

          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-ink-100 px-5 py-2.5 text-xs">
            <span className="text-ink-500">Другой разрез:</span>
            <a href="#compare" className="inline-flex items-center gap-1 text-ink-700 hover:underline">эта новость для других компаний <ArrowRight size={12} /></a>
            {a.event.category && <Link to={`/feed?category=${a.event.category}&sort=priority`} className="inline-flex items-center gap-1 text-ink-700 hover:underline">все события темы <ArrowRight size={12} /></Link>}
            <a href="#thread" className="inline-flex items-center gap-1 text-ink-700 hover:underline">развитие сюжета <ArrowRight size={12} /></a>
            <Link to="/bank" className="inline-flex items-center gap-1 text-ink-700 hover:underline">аналитика банка <ArrowRight size={12} /></Link>
          </div>

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
