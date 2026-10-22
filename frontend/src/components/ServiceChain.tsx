import { ExternalLink, Link2 } from "lucide-react";
import { Link } from "react-router-dom";
import type { Interpretation, MatchResult, Statement } from "../types";
import { formatDate } from "../utils";

// цепочка сервисов (C20.8): объяснение для руководителя (сервис 4) по результату сопоставления (сервис 3)
const KIND: Record<Statement["kind"], { label: string; cls: string }> = {
  fact: { label: "Факт", cls: "bg-sky-50 text-sky-800" },
  link: { label: "Связь", cls: "bg-emerald-50 text-emerald-800" },
  assumption: { label: "Допущение", cls: "bg-amber-50 text-amber-800" },
  recommendation: { label: "Рекомендация", cls: "bg-violet-50 text-violet-800" },
  uncertainty: { label: "Неопределённость", cls: "bg-ink-100 text-ink-600" },
  bank: { label: "Позиция банка", cls: "bg-rose-50 text-rose-800" },
};
const RELATION: Record<string, string> = { agree: "совпадает с новостью", conflict: "расходится с новостью", context: "дополняет" };
const LEVEL: Record<Interpretation["uncertainty"]["level"], { label: string; cls: string }> = {
  low: { label: "низкая", cls: "bg-emerald-50 text-emerald-800" },
  medium: { label: "средняя", cls: "bg-amber-50 text-amber-800" },
  high: { label: "высокая", cls: "bg-rose-50 text-rose-800" },
};
const LLM_STATUS: Record<string, string> = {
  done: "проверены моделью", cached: "проверены моделью (из кэша)", not_checked: "не проверены моделью",
  failed: "модель недоступна — не проверены",
};

function RefChip({ id, m }: { id: string; m: MatchResult | null | undefined }) {
  const cls = "rounded bg-ink-50 px-1 py-0.5 text-[11px] text-ink-500 ring-1 ring-ink-100";
  if (id.startsWith("news:")) {
    const n = m?.news.find((x) => x.event_id === id.slice(5));
    return n?.url ? <a href={n.url} target="_blank" rel="noreferrer" className={`${cls} hover:text-ink-900`}>{n.source}</a>
      : <span className={cls}>{n?.source || "новость"}</span>;
  }
  if (id.startsWith("p:")) {
    const f = m?.profile_facts.find((x) => x.id === id);
    return <Link to="/profile" className={`${cls} hover:text-ink-900`} title={f ? `${f.label}: ${f.value}` : id}>{f?.label || id}</Link>;
  }
  if (id.startsWith("bank:")) {
    const b = m?.bank?.find((x) => x.source === id);
    return b ? <a href={b.url} target="_blank" rel="noreferrer" className={`${cls} hover:text-ink-900`}>{b.title}, стр. {b.page}</a>
      : <span className={cls}>аналитика банка</span>;
  }
  if (id.startsWith("link:")) return <span className={cls}>связь {Number(id.slice(5)) + 1}</span>;
  if (id.startsWith("assumption:")) return <span className={cls}>допущение {Number(id.slice(11)) + 1}</span>;
  return <span className={cls}>балл правил</span>;
}

function Statements({ items, m }: { items: Statement[]; m?: MatchResult | null }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((st, i) => (
        <li key={i} className="flex flex-col gap-1 text-sm sm:flex-row sm:items-start sm:gap-2">
          <span className={`w-fit shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${KIND[st.kind].cls}`}>{KIND[st.kind].label}</span>
          <span className="text-ink-800">{st.text} <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
            {st.refs.map((r) => <RefChip key={r} id={r} m={m} />)}</span></span>
        </li>
      ))}
    </ul>
  );
}

export default function ServiceChain({ i, m }: { i: Interpretation; m?: MatchResult | null }) {
  return (
    <section className="border-b border-ink-100 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink-900">Объяснение для руководителя</h3>
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${LEVEL[i.uncertainty.level].cls}`}>
          неопределённость {LEVEL[i.uncertainty.level].label}
        </span>
        <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[11px] text-ink-600">
          {i.mode === "llm" ? `сформулировала модель${i.llm.mock ? " (тестовый режим)" : ""}` : "по шаблону, без модели"}
        </span>
      </div>
      <p className="mt-2 font-medium text-ink-900">{i.headline}</p>
      <p className="mt-0.5 text-xs text-ink-500">Только по результату сопоставления с профилем из данных банка: новых фактов
        объяснение не добавляет; у каждого утверждения — ссылка на новость, факт профиля, связь или балл.</p>
      <div className="mt-3 space-y-3">
        <Statements items={i.why_it_matters} m={m} />
        <Statements items={i.what_to_do} m={m} />
        {i.uncertainty.reasons.length > 0 && (
          <p className="text-xs text-ink-600"><b className="font-medium">Почему неопределённость:</b> {i.uncertainty.reasons.join("; ")}</p>
        )}
        {i.not_known.length > 0 && (
          <p className="text-xs text-ink-600"><b className="font-medium">Чего нет в данных:</b> {i.not_known.join("; ")}</p>
        )}
      </div>
      {m && (
        <details className="mt-3 rounded-lg bg-ink-50 px-3 py-2 text-sm">
          <summary className="cursor-pointer text-ink-700">
            <Link2 size={13} className="mr-1 inline" />
            Сопоставление с профилем: значимость {m.score.priority}/100 по правилам · подтверждённых связей {m.links.length},
            допущений {m.assumptions.length} · связи {LLM_STATUS[m.llm.status] || m.llm.status}
          </summary>
          <div className="mt-2 space-y-3 text-xs text-ink-700">
            <p>{m.explanation}</p>
            <div>
              <div className="font-medium text-ink-900">Подтверждённые связи (факт профиля + цитата из новости)</div>
              {m.links.length ? (
                <ol className="mt-1 list-decimal space-y-1 pl-4">
                  {m.links.map((l, k) => (
                    <li key={k}>{m.profile_facts.find((f) => f.id === l.fact_id)?.label || l.fact_id}: «{l.news_quote}» — {l.explanation}</li>
                  ))}
                </ol>
              ) : <p className="mt-1 text-ink-500">Нет{m.llm.reason ? `: ${m.llm.reason}` : ""}.</p>}
            </div>
            {m.assumptions.length > 0 && (
              <div>
                <div className="font-medium text-ink-900">Допущения</div>
                <ol className="mt-1 list-decimal space-y-1 pl-4">
                  {m.assumptions.map((a, k) => <li key={k}>{a.text} <span className="text-ink-500">({a.reason})</span></li>)}
                </ol>
              </div>
            )}
            <div>
              <div className="font-medium text-ink-900">Позиция Альфа-Банка по этой новости</div>
              {m.bank && m.bank.some((b) => b.quote) ? (
                <ul className="mt-1 space-y-1">
                  {m.bank.filter((b) => b.quote).map((b) => (
                    <li key={b.source}>«{b.quote}» — <a href={b.url} target="_blank" rel="noreferrer" className="hover:underline">
                      {b.title}{b.date ? `, ${b.date}` : ""}, стр. {b.page}</a> <span className="text-ink-500">({RELATION[b.relation]})</span></li>
                  ))}
                </ul>
              ) : <p className="mt-1 text-ink-500">В аналитике банка нет фрагментов с позицией по этой новости.</p>}
            </div>
            {m.profile_facts.length > 0 && (
              <div>
                <div className="font-medium text-ink-900">Факты профиля, на которые опирается оценка</div>
                <ul className="mt-1 space-y-0.5">
                  {m.profile_facts.map((f) => <li key={f.id}><Link to="/profile" className="hover:underline">{f.label}</Link>: {f.value}</li>)}
                </ul>
              </div>
            )}
            <div>
              <div className="font-medium text-ink-900">Публикации</div>
              <ul className="mt-1 space-y-0.5">
                {m.news.map((n) => (
                  <li key={n.event_id}>{n.source}, {formatDate(n.published_at)}
                    {n.url && <a href={n.url} target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center gap-0.5 text-ink-500 hover:text-ink-900">
                      оригинал <ExternalLink size={11} /></a>}</li>
                ))}
              </ul>
            </div>
          </div>
        </details>
      )}
    </section>
  );
}
