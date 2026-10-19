import { Rss } from "lucide-react";
import { api } from "../api";
import { useLoad } from "../context";
import Modal from "./Modal";
import { ErrorBox, Loading } from "./States";

const COUNTRY: Record<string, string> = { RU: "Россия", KZ: "Казахстан", BY: "Беларусь", UZ: "Узбекистан", INT: "Международное" };

// реестр изданий и правила достоверности (backend/data/outlets.json, app/outlets.py)
export default function SourcesModal({ onClose }: { onClose: () => void }) {
  const { data, loading, error, reload } = useLoad(() => api.outlets(), []);
  return (
    <Modal title="Источники и их репутация" onClose={onClose} wide>
      <div className="space-y-3 text-sm text-ink-700">
        <p>
          Достоверность новости (0–100) складывается из двух вещей: <b>репутации издания</b> (официальный источник,
          информационное агентство, деловое издание, отраслевое, агрегатор) и <b>числа независимых изданий</b>, которые
          написали то же самое. Перепечатки внутри одного медиахолдинга (например, РИА и ПРАЙМ) независимыми не считаются.
        </p>
        <p className="rounded-lg bg-ink-50 px-3 py-2 text-xs">
          Формула: репутация лучшего издания × 70 + независимые издания (2 — +12, 3 — +20, 4 и больше — +25) +
          официальный источник +15 − подозрительный текст 30. От 80 — высокая, 60–79 — средняя, ниже — проверьте
          первоисточник. Российские издания — около 90% ленты, зарубежные (русскоязычные издания Казахстана, Беларуси,
          Узбекистана) — не больше 10%.
        </p>
      </div>
      {loading && !data && <Loading text="Загружаем реестр изданий…" />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-left text-xs text-ink-500">
                <th className="py-2 pr-3 font-medium">Издание</th>
                <th className="py-2 pr-3 font-medium">Тип</th>
                <th className="py-2 pr-3 font-medium">Страна</th>
                <th className="py-2 pr-3 font-medium">Холдинг</th>
                <th className="py-2 font-medium">Репутация</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {data.map((o) => (
                <tr key={o.name}>
                  <td className="py-1.5 pr-3">
                    <span className="font-medium">{o.name}</span>
                    {o.rss && <span className="ml-1.5 inline-flex items-center gap-0.5 rounded bg-emerald-50 px-1 text-[10px] font-medium text-emerald-700"
                      title="Загружается в ленту по RSS"><Rss size={9} /> RSS</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-xs text-ink-500">{o.tier_label}</td>
                  <td className="py-1.5 pr-3 text-xs text-ink-500">{COUNTRY[o.country] || o.country}</td>
                  <td className="py-1.5 pr-3 text-xs text-ink-500">{o.holding}</td>
                  <td className="py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="block h-1.5 w-16 rounded-full bg-ink-100">
                        <span className="block h-1.5 rounded-full bg-ink-700" style={{ width: `${o.reputation * 100}%` }} />
                      </span>
                      <span className="tabular-nums text-xs">{o.reputation.toFixed(2)}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-ink-400">Издания без отметки RSS встречаются в проверенной подборке публикаций.</p>
        </div>
      )}
    </Modal>
  );
}
