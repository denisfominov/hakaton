import { Cpu } from "lucide-react";
import type { CaseMl } from "../types";

const IMPACT: Record<string, string> = { risk: "риск", opportunity: "возможность", neutral: "нейтрально" };
const URGENCY: Record<string, string> = { high: "высокая", medium: "средняя", low: "низкая" };
const CATEGORY: Record<string, string> = {
  economy: "Экономика", regulation: "Регулирование", markets: "Рынки", companies: "Компании и конкуренты",
  technology: "Технологии", supply_chain: "Цепочки поставок", investment: "Инвестиции", industry: "Отраслевые изменения",
  other: "Прочее",
};
const MODEL: Record<string, string> = { logreg: "логистическая регрессия", hgb: "градиентный бустинг", tfidf_logreg: "TF-IDF + логрегрессия", tfidf_nb: "TF-IDF + наивный Байес" };

// своя модель (не LLM) по данным клиента кейса: вероятность значимости и вклад признаков компании
export default function CaseModelPanel({ m }: { m: CaseMl }) {
  const contrib = m.relevance.contributions;
  const max = Math.max(0.001, ...contrib.map((c) => Math.abs(c.contribution)));
  return (
    <section className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <h2 className="section-title flex items-center gap-1.5"><Cpu size={15} /> Своя модель по данным клиента</h2>
        {m.draft && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800" title="Пока нет ручной разметки 200+ пар: модели обучены на синтетике и слабой разметке правилами">черновая</span>}
      </div>
      <p className="text-xs text-ink-500">Не LLM: {MODEL[m.relevance.model] || m.relevance.model} на признаках компании и графа контрагентов из данных кейса.</p>
      <div className="mt-3 flex items-baseline justify-between text-sm">
        <span className="text-ink-600">Вероятность, что событие значимо</span>
        <b className="tabular-nums">{Math.round(m.relevance.probability * 100)}%</b>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-ink-100"><div className="h-1.5 rounded-full bg-ink-800" style={{ width: `${m.relevance.probability * 100}%` }} /></div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        {m.impact && <div><div className="text-ink-500">Влияние</div><div className="font-medium">{IMPACT[m.impact.label] || m.impact.label}</div></div>}
        {m.urgency && <div><div className="text-ink-500">Срочность</div><div className="font-medium">{URGENCY[m.urgency.label] || m.urgency.label}</div></div>}
        {m.category && <div><div className="text-ink-500">Категория</div><div className="font-medium">{CATEGORY[m.category.label] || m.category.label}</div></div>}
      </div>
      {contrib.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium text-ink-700">Что повлияло на вывод</div>
          <ul className="space-y-1">
            {contrib.map((c) => (
              <li key={c.feature} className="text-xs">
                <div className="flex justify-between gap-2"><span className="text-ink-700">{c.label}</span>
                  <span className={`tabular-nums ${c.contribution > 0 ? "text-emerald-700" : "text-rose-700"}`}>{c.contribution > 0 ? "+" : ""}{c.contribution.toFixed(2)}</span></div>
                <div className="mt-0.5 h-1 rounded-full bg-ink-100">
                  <div className={`h-1 rounded-full ${c.contribution > 0 ? "bg-emerald-500" : "bg-rose-500"}`} style={{ width: `${(Math.abs(c.contribution) / max) * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.company_features.length > 0 && (
        <details className="mt-3 text-xs text-ink-600">
          <summary className="cursor-pointer text-ink-500">Признаки компании</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">{m.company_features.map((f) => <li key={f}>{f}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
