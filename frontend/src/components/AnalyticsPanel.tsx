import { Bot, Cpu, GraduationCap, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import { useApp, useLoad } from "../context";
import type { ModelCv, ModelFeature } from "../types";
import { formatDate } from "../utils";
import Modal from "./Modal";
import { ErrorBox, Loading } from "./States";

function Layer({ icon: Icon, title, state, tone, children }: {
  icon: typeof Cpu; title: string; state: string; tone: string; children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-ink-200 p-4">
      <div className="flex items-center gap-2">
        <Icon size={16} className="text-ink-500" />
        <h3 className="flex-1 text-sm font-semibold">{title}</h3>
        <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}>{state}</span>
      </div>
      <div className="mt-2 space-y-2 text-sm text-ink-700">{children}</div>
    </div>
  );
}

function Cv({ cv }: { cv: ModelCv | null }) {
  if (!cv) return <p className="text-xs text-ink-500">Качество оценим, когда в каждом классе будет хотя бы 2 оценки.</p>;
  const better = cv.model_accuracy - cv.rules_accuracy;
  return (
    <p className="text-xs text-ink-500">
      Проверка на отложенных оценках ({cv.folds}-кратная кросс-валидация): модель угадывает
      <b className="text-ink-900"> {Math.round(cv.model_accuracy * 100)}%</b>, правила —
      <b className="text-ink-900"> {Math.round(cv.rules_accuracy * 100)}%</b>
      {better > 0.001 ? " — модель уже лучше правил." : better < -0.001 ? " — пока хуже правил, нужно больше оценок." : " — пока на уровне правил."}
    </p>
  );
}

function Features({ title, items, tone }: { title: string; items: ModelFeature[]; tone: string }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="text-xs font-medium text-ink-500">{title}</div>
      <ul className="mt-1 flex flex-wrap gap-1.5">
        {items.map((f) => (
          <li key={f.name} className={`rounded-md px-2 py-0.5 text-xs ${tone}`} title={`вес ${f.weight}`}>{f.label}</li>
        ))}
      </ul>
    </div>
  );
}

// что стоит за бейджем «Аналитика»: правила, своя модель на оценках пользователя, LLM по кнопке
export default function AnalyticsPanel({ onClose }: { onClose: () => void }) {
  const { status, reloadStatus, bumpData, toast } = useApp();
  const { data: m, setData, loading, error, reload } = useLoad(() => api.model(), []);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<typeof m>, msg: string) => {
    setBusy(true);
    try {
      const res = await fn();
      if (res) setData(res);
      await reloadStatus();
      bumpData();
      toast(msg);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const left = m ? Math.max(0, m.min_labels - m.labels.relevance) : 0;

  return (
    <Modal title="Как устроена аналитика" onClose={onClose} wide>
      <p className="text-sm text-ink-700">
        Сервис не пересылает новости в чужую модель «как есть». Оценки считает собственный движок в три слоя,
        и каждый балл можно разложить на причины.
      </p>
      <div className="mt-4 space-y-3">
        <Layer icon={Cpu} title="1. Правила по профилю компании" state="Работают всегда" tone="bg-emerald-50 text-emerald-700">
          <p>Находят в новости то, что есть в профиле (продукты, поставщики, конкуренты, регионы, риски), определяют
            канал влияния — рост затрат, сбой поставок, спрос, ставка, господдержка — и считают релевантность, влияние,
            срочность и уверенность. Работают офлайн, без ключей.</p>
        </Layer>

        <Layer icon={GraduationCap} title="2. Своя модель — учится на ваших оценках"
          state={!m ? "…" : m.active ? `Активна · вес ${Math.round(m.weight * 100)}%` : m.trained ? "Выключена" : "Копит оценки"}
          tone={m?.active ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}>
          <p>На странице события ответьте, относится ли новость к компании, риск это или возможность и верна ли важность.
            На этих оценках обучаются две логистические регрессии (scikit-learn, локально): «значимо ли для компании» и
            «тип влияния». Признаки — что нашли правила плюс слова новости в связке с отраслью. Модель сдвигает
            релевантность (не больше чем на {Math.round((m?.max_weight ?? 0.5) * 100)}%), поправка видна отдельной строкой в разложении балла.
            Ваша оценка конкретного события учитывается сразу.</p>
          {loading && !m && <Loading text="Загружаем состояние модели…" />}
          {error && <ErrorBox error={error} onRetry={reload} />}
          {m && (
            <div className="space-y-3 rounded-lg bg-ink-50 p-3">
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div><div className="text-ink-500">Оценок «относится?»</div><div className="text-lg font-semibold tabular-nums">{m.labels.relevance}</div></div>
                <div><div className="text-ink-500">Да / нет</div><div className="text-lg font-semibold tabular-nums">{m.labels.relevant} / {m.labels.not_relevant}</div></div>
                <div><div className="text-ink-500">Тип влияния</div><div className="text-lg font-semibold tabular-nums">{m.labels.impact}</div></div>
                <div><div className="text-ink-500">Важность</div><div className="text-lg font-semibold tabular-nums">{m.labels.priority}</div></div>
              </div>
              {!m.trained && (
                <p className="text-xs text-ink-700">
                  До обучения: ещё {left > 0 ? left : 0} {left > 0 ? "оценок" : ""} — нужно минимум {m.min_labels}, среди них хотя бы
                  2 «да» и 2 «нет». Полный вес модель получит на {m.full_weight_at} оценках.
                </p>
              )}
              {m.relevance && (
                <>
                  <Cv cv={m.relevance.cv} />
                  <Features title="Чаще всего делает новость значимой" items={m.relevance.top.positive} tone="bg-emerald-50 text-emerald-800" />
                  <Features title="Чаще всего делает новость незначимой" items={m.relevance.top.negative} tone="bg-rose-50 text-rose-800" />
                  <p className="text-xs text-ink-400">Обучена {formatDate(m.relevance.trained_at)} на {m.relevance.n} оценках.
                    {m.impact ? ` Модель типа влияния: ${m.impact.n} оценок.` : " Модель типа влияния ждёт оценок."}</p>
                </>
              )}
              {m.by_profile.length > 0 && (
                <p className="text-xs text-ink-500">По компаниям: {m.by_profile.map((p) => `${p.name} — ${p.count}`).join("; ")}</p>
              )}
              <div className="flex flex-wrap gap-2">
                <button className="btn-secondary !py-1.5 text-xs" disabled={busy || !m.labels.total}
                  onClick={() => run(api.trainModel, "Модель переобучена")}>
                  <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> Переобучить
                </button>
                {m.trained && (
                  <button className="btn-ghost !py-1.5 text-xs" disabled={busy}
                    onClick={() => run(() => api.setModelEnabled(!m.enabled),
                      m.enabled ? "Модель выключена — баллы только по правилам" : "Модель включена")}>
                    {m.enabled ? "Выключить и сравнить с правилами" : "Включить модель"}
                  </button>
                )}
              </div>
            </div>
          )}
        </Layer>

        <Layer icon={Bot} title="3. LLM — по кнопке, для текста разбора"
          state={status?.llm.enabled ? `Подключена (${status.llm.model})` : "Не подключена"}
          tone={status?.llm.enabled ? "bg-emerald-50 text-emerald-700" : "bg-ink-100 text-ink-500"}>
          <p>Языковая модель (Claude) только переписывает разбор понятным языком по структурированной схеме, а факты
            сверяются с текстом источника. Баллы и ранжирование она не меняет. Вызывается вручную на странице события,
            без ключа сервис полностью работает на слоях 1–2.</p>
        </Layer>
      </div>
      <p className="mt-4 text-xs text-ink-400">
        Почему не своя большая языковая модель: для неё нужны тысячи размеченных примеров и GPU. Оценки пользователей —
        это и есть разметка; когда их наберутся сотни, на них можно дообучить компактную русскоязычную модель
        (например, ruBERT) вместо логистической регрессии.
      </p>
    </Modal>
  );
}
