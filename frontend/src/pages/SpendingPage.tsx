import { AlertTriangle, Info } from "lucide-react";
import { api } from "../api";
import { ErrorBox, Skeleton } from "../components/States";
import { useLoad } from "../context";

const rub = (v: number) => `${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
const num = (v: number) => v.toLocaleString("ru-RU");
const PROVIDER: Record<string, string> = {
  off: "LLM выключена — работают правила и свои ML-модели",
  mock: "мок-режим шлюза: ответы без модели и без сети",
  gateway: "шлюз организаторов",
};

// расход LLM: дневной лимит кейса (500 ₽), токены и стоимость по моделям, маршруты моделей, версии промптов
export default function SpendingPage() {
  const { data, loading, error, reload } = useLoad(() => api.llmUsage(14), []);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (loading && !data) return <Skeleton rows={4} />;
  if (!data) return null;
  const share = data.limit_rub ? Math.min(100, (data.spent_rub / data.limit_rub) * 100) : 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Расход</h1>
        <p className="mt-1 text-sm text-ink-500">
          Токены и стоимость вызовов LLM за день. Лимит кейса — эквивалент 500 ₽ в день на общий ключ; сервис держит
          жёсткий лимит ниже и при его исчерпании отвечает правилами или из кэша с пометкой.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded-md bg-ink-100 px-2 py-1 text-ink-700">Режим: {PROVIDER[data.provider] || data.provider}</span>
        {!data.verified && (
          <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-amber-800">
            <AlertTriangle size={12} /> Реальные вызовы шлюза не проверялись: ключа пока нет
          </span>
        )}
        {data.prices_assumed && <span className="rounded-md bg-amber-50 px-2 py-1 text-amber-800">Цены моделей — допущение (LLM_PRICE_*)</span>}
      </div>

      <section className="card p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs text-ink-500">Сегодня, {data.today}</div>
            <div className="text-2xl font-semibold tabular-nums">{rub(data.spent_rub)} <span className="text-base font-normal text-ink-500">из {rub(data.limit_rub)}</span></div>
          </div>
          <div className="text-right text-sm text-ink-600">
            Осталось {rub(data.remaining_rub)} · токенов {num(data.tokens)}{data.token_limit ? ` из ${num(data.token_limit)}` : ""}
          </div>
        </div>
        <div className="mt-3 h-2 rounded-full bg-ink-100">
          <div className={`h-2 rounded-full ${share >= 90 ? "bg-rose-600" : share >= 70 ? "bg-amber-500" : "bg-emerald-600"}`} style={{ width: `${share}%` }} />
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="card overflow-hidden">
          <h2 className="section-title px-4 pt-4">По моделям сегодня</h2>
          <table className="w-full text-sm">
            <thead><tr className="border-b border-ink-200 text-left text-xs text-ink-500">
              <th className="px-4 py-2 font-medium">Модель</th><th className="px-2 py-2 text-right font-medium">Вызовы</th>
              <th className="px-2 py-2 text-right font-medium">Кэш</th><th className="px-2 py-2 text-right font-medium">Токены</th>
              <th className="px-4 py-2 text-right font-medium">₽</th></tr></thead>
            <tbody className="divide-y divide-ink-100">
              {data.by_model.map((m) => (
                <tr key={m.model}><td className="px-4 py-2">{m.model}{m.errors ? <span className="ml-1 text-xs text-rose-700">· ошибок {m.errors}</span> : null}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{m.calls}</td><td className="px-2 py-2 text-right tabular-nums">{m.cache_hits}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{num(m.prompt_tokens + m.completion_tokens)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{rub(m.rub)}</td></tr>
              ))}
              {!data.by_model.length && <tr><td colSpan={5} className="px-4 py-4 text-center text-xs text-ink-400">Сегодня вызовов не было</td></tr>}
            </tbody>
          </table>
        </section>

        <section className="card overflow-hidden">
          <h2 className="section-title px-4 pt-4">По дням</h2>
          <table className="w-full text-sm">
            <thead><tr className="border-b border-ink-200 text-left text-xs text-ink-500">
              <th className="px-4 py-2 font-medium">День</th><th className="px-2 py-2 text-right font-medium">Вызовы</th>
              <th className="px-2 py-2 text-right font-medium">Кэш</th><th className="px-2 py-2 text-right font-medium">Ошибки</th>
              <th className="px-4 py-2 text-right font-medium">₽</th></tr></thead>
            <tbody className="divide-y divide-ink-100">
              {data.by_day.map((d) => (
                <tr key={d.day}><td className="px-4 py-2">{d.day}</td><td className="px-2 py-2 text-right tabular-nums">{d.calls}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{d.cache_hits}</td><td className="px-2 py-2 text-right tabular-nums">{d.errors}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{rub(d.rub)}</td></tr>
              ))}
              {!data.by_day.length && <tr><td colSpan={5} className="px-4 py-4 text-center text-xs text-ink-400">Пока пусто</td></tr>}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card overflow-hidden">
        <h2 className="section-title px-4 pt-4">Маршруты моделей</h2>
        <p className="px-4 text-xs text-ink-500">Тип задачи → основная модель и запасная на случай ошибки, таймаута или лимита. Только модели из списка кейса.</p>
        <table className="mt-2 w-full text-sm">
          <tbody className="divide-y divide-ink-100">
            {data.routes.map((r) => (
              <tr key={r.task}><td className="px-4 py-2 text-ink-700">{r.label}</td><td className="px-2 py-2 font-medium">{r.primary}</td>
                <td className="px-4 py-2 text-xs text-ink-500">{r.fallback.length ? `запасная: ${r.fallback.join(", ")}` : "без запасной (OCR без LLM)"}</td>
                <td className="px-4 py-2 text-right text-xs tabular-nums text-ink-500">
                  {data.prices[r.primary] ? `${data.prices[r.primary].input} / ${data.prices[r.primary].output} ₽ за 1 млн` : ""}
                </td></tr>
            ))}
          </tbody>
        </table>
        <p className="flex gap-1.5 border-t border-ink-100 px-4 py-2.5 text-xs text-ink-500">
          <Info size={13} className="mt-0.5 shrink-0" /> Промпты: {data.prompts.map((p) => `${p.name}@${p.version}`).join(", ")}.
        </p>
      </section>

      {data.errors.length > 0 && (
        <section className="card p-4">
          <h2 className="section-title">Последние ошибки</h2>
          <ul className="mt-2 space-y-1 text-xs text-ink-600">
            {data.errors.map((e, i) => <li key={i}>{e.ts} · {e.model} · {e.purpose}: {e.error}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}
