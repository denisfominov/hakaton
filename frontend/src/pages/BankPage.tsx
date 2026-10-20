import { FileText, Info } from "lucide-react";
import { api } from "../api";
import { Empty, ErrorBox, Skeleton } from "../components/States";
import { useLoad } from "../context";

// аналитика Альфа-Банка, на которую опирается агент: документы, темы, ключевые тезисы со страницами
export default function BankPage() {
  const { data, loading, error, reload } = useLoad(() => api.bankDocs(), []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Аналитика банка</h1>
        <p className="mt-1 text-sm text-ink-500">
          Материалы Центра макроэкономических исследований Альфа-Банка. Агент ищет в них позицию банка по каждому событию
          и цитирует только найденные фрагменты — со ссылкой на документ и страницу.
        </p>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton rows={3} />}

      {data && data.documents.length === 0 && (
        <Empty title="Материалы банка не загружены"
          text="Положите PDF или тексты аналитики (приложение 2 кейса) в папку backend/data/bank или укажите папку в BANK_DOCS_DIR. Индекс соберётся сам при следующем запросе; до этого агент честно пишет, что позиции банка нет." />
      )}

      {data && data.documents.length > 0 && (
        <>
          <p className="flex gap-1.5 text-xs text-ink-500">
            <Info size={13} className="mt-0.5 shrink-0" /> Документов: {data.documents.length}, фрагментов в поиске: {data.chunks}.
            Темы определены по словарю, ключевые тезисы — предложения с прогнозом или оценкой банка.
          </p>
          <div className="grid gap-3 lg:grid-cols-2">
            {data.documents.map((d) => (
              <article key={d.file} className="card flex flex-col p-4">
                <div className="flex items-start gap-2">
                  <FileText size={16} className="mt-0.5 shrink-0 text-rose-600" />
                  <div className="min-w-0">
                    <h2 className="font-semibold leading-snug">{d.title}</h2>
                    <div className="mt-0.5 text-xs text-ink-500">{d.file} · стр. {d.pages}{d.date ? ` · ${d.date}` : ""}</div>
                  </div>
                </div>
                {d.topics.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {d.topics.map((t) => <span key={t} className="rounded bg-rose-50 px-1.5 py-0.5 text-xs text-rose-800">{data.topics[t] || t}</span>)}
                  </div>
                )}
                {d.theses.length > 0 ? (
                  <ul className="mt-3 space-y-1.5 text-sm text-ink-800">
                    {d.theses.map((t) => (
                      <li key={t.chunk + t.text.slice(0, 20)} className="flex gap-2">
                        <span className="shrink-0 text-xs text-ink-400">стр. {t.page}</span>
                        <span>{t.text}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="mt-3 text-xs text-ink-400">Явных прогнозов в тексте не найдено — документ участвует в поиске целиком.</p>}
              </article>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
