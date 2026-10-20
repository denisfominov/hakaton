import { Bot, Cpu, GraduationCap, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import { useApp, useLoad } from "../context";
import type { ModelCv, ModelFeature, ModelStatus } from "../types";
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

const METRIC_LABEL: Record<string, string> = { pr_auc: "PR-AUC", macro_f1: "macro-F1" };

function Cv({ cv }: { cv: ModelCv | null }) {
  if (!cv) return <p className="text-xs text-ink-500">Качество оценим, когда в каждом классе будет хотя бы 2 оценки.</p>;
  if (!cv.metric || !cv.model || !cv.rules) {
    const better = cv.model_accuracy - cv.rules_accuracy;
    return (
      <p className="text-xs text-ink-500">
        Кросс-валидация ({cv.folds} фолдов): модель {Math.round(cv.model_accuracy * 100)}%, правила {Math.round(cv.rules_accuracy * 100)}%
        {better > 0.001 ? " — модель лучше правил." : " — модель не лучше правил."}
      </p>
    );
  }
  const key = cv.metric;
  const m = cv.model[key] ?? 0;
  const r = cv.rules[key] ?? 0;
  const pct = (v?: number) => (v === undefined ? "—" : v.toFixed(2));
  return (
    <div className="space-y-1 text-xs text-ink-500">
      <p>
        Проверка на отложенных метках ({cv.folds} фолдов, {cv.scheme}{cv.positive_share !== undefined ? `, доля значимых ${Math.round(cv.positive_share * 100)}%` : ""}).
        Главная метрика — <b className="text-ink-900">{METRIC_LABEL[key]}</b>: модель <b className="text-ink-900">{pct(m)}</b>,
        правила <b className="text-ink-900">{pct(r)}</b>{m > r ? " — модель лучше правил." : " — модель пока хуже правил, её голос уменьшен вдвое."}
      </p>
      {key === "pr_auc" && (
        <p>
          ROC-AUC {pct(cv.model.roc_auc)} / {pct(cv.rules.roc_auc)} · precision {pct(cv.model.precision)} / {pct(cv.rules.precision)} ·
          recall {pct(cv.model.recall)} / {pct(cv.rules.recall)} · F1 {pct(cv.model.f1)} / {pct(cv.rules.f1)} (модель / правила) ·
          калибровка (Brier) {pct(cv.model.brier)}{cv.C ? ` · C = ${cv.C}` : ""}. Accuracy не используем: при редком классе она завышена.
        </p>
      )}
    </div>
  );
}

function MarketBlock({ m, busy, onRefresh }: { m: ModelStatus; busy: boolean; onRefresh: (prices: boolean) => void }) {
  const mk = m.market;
  const origin: Record<string, string> = { history: "история", curated: "подборка", rss: "RSS", alfa: "Альфа" };
  return (
    <div className="rounded-lg border border-ink-200 bg-white p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium text-ink-900">Разметка по реакции рынка</div>
        <div className="flex gap-1.5">
          <button className="btn-ghost !px-2 !py-1 text-xs" disabled={busy} onClick={() => onRefresh(false)}>Пересчитать</button>
          <button className="btn-secondary !px-2 !py-1 text-xs" disabled={busy} onClick={() => onRefresh(true)}
            title="Докачать свежие котировки с Мосбиржи (нужен интернет) и разметить новости">
            <RefreshCw size={12} className={busy ? "animate-spin" : ""} /> Обновить котировки
          </button>
        </div>
      </div>
      <p className="mt-1 text-ink-700">
        Меток: <b>{mk.labels}</b> — «значимо» {mk.significant}, «рынок не заметил» {mk.quiet}
        {Object.keys(mk.by_origin).length > 0 && <> (по источникам: {Object.entries(mk.by_origin).map(([k, v]) => `${origin[k] || k} ${v}`).join(", ")})</>}.
        Неоднозначных (не используются): {mk.ambiguous}. Акции: {mk.tickers.join(", ") || "нет публичных компаний"};
        котировки до {mk.prices_until ? formatDate(mk.prices_until, false) : "—"}
      </p>
      <p className="mt-1 text-ink-500">
        «Значимо» — отклонение от индекса больше {mk.significant_z} обычных колебаний (вес {mk.weight});
        «не заметил» — меньше {mk.quiet_z}, и только если правила тоже считают новость слабой (релевантность до
        {" "}{mk.quiet_max_rule_relevance}, вес {mk.quiet_weight}): бизнесу событие может быть важно, даже если акции стоят.
      </p>
      {mk.examples.length > 0 && (
        <ul className="mt-2 space-y-1">
          {mk.examples.map((e) => (
            <li key={e.event_id + e.ticker} className="flex gap-2">
              <span className={`w-14 shrink-0 text-right font-semibold tabular-nums ${e.ar < 0 ? "text-rose-700" : "text-emerald-700"}`}>
                {e.ar > 0 ? "+" : ""}{e.ar}%
              </span>
              <span className="min-w-0 text-ink-700">
                {e.ticker}: {e.title} <span className="text-ink-400">({formatDate(e.t0, false)}, z = {e.z})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
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

        <Layer icon={GraduationCap} title="2. Своя модель — учится на оценках и на реакции рынка"
          state={!m ? "…" : m.active ? `Активна · вес ${Math.round(m.weight * 100)}%` : m.trained ? "Выключена" : "Копит метки"}
          tone={m?.active ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}>
          <p>Две логистические регрессии (scikit-learn, локально): «значимо ли для компании» и «тип влияния». Признаки —
            что нашли правила плюс слова новости в связке с отраслью. Модель сдвигает релевантность (не больше чем на
            {" "}{Math.round((m?.max_weight ?? 0.5) * 100)}%), поправка видна отдельной строкой в разложении балла.</p>
          <p><b>Учителя два.</b> Первый — ваши оценки на странице события (относится ли, риск или возможность, верна ли
            важность); оценка конкретного события учитывается сразу. Второй — рынок: для публичных компаний сервис
            смотрит, как акции отклонились от индекса Мосбиржи за {m?.market.horizon ?? 2} торговых дня после новости, —
            в том числе на старых новостях. Так модель учится и без оценок, но рыночные метки шумные, поэтому их вес
            меньше, а одни они дают модели не больше {Math.round((m?.auto_max_weight ?? 0.25) * 100)}% голоса.</p>
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
              <MarketBlock m={m} busy={busy} onRefresh={(prices) => run(async () => (await api.marketRefresh(prices)).model,
                prices ? "Котировки обновлены, разметка пересчитана" : "Разметка пересчитана")} />
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
                  <p className="text-xs text-ink-400">Обучена {formatDate(m.relevance.trained_at)}: {m.relevance.n_user ?? 0} оценок
                    пользователя и {m.relevance.n_market ?? 0} рыночных меток.
                    {m.impact ? ` Модель типа влияния: ${m.impact.n} оценок.` : " Модель типа влияния ждёт оценок."}</p>
                </>
              )}
              {m.by_profile.length > 0 && (
                <p className="text-xs text-ink-500">По компаниям: {m.by_profile.map((p) => `${p.name} — ${p.count}`).join("; ")}</p>
              )}
              <div className="flex flex-wrap gap-2">
                <button className="btn-secondary !py-1.5 text-xs" disabled={busy}
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
          state={!status ? "…" : status.llm.state === "gateway" ? `${status.llm.label} (${status.llm.model})` : status.llm.label}
          tone={status?.llm.state === "gateway" ? "bg-emerald-50 text-emerald-700"
            : status?.llm.state === "budget" || status?.llm.state === "mock" ? "bg-amber-50 text-amber-800" : "bg-ink-100 text-ink-500"}>
          <p>Языковая модель (только разрешённые кейсом: Qwen3.6, GLM-5.3, Gemma 4 и др. — через шлюз организаторов) переписывает разбор понятным языком по структурированной схеме, а факты
            сверяются с текстом источника. Баллы и ранжирование она не меняет. Вызывается вручную на странице события,
            без языковой модели сервис полностью работает на слоях 1–2.</p>
        </Layer>
      </div>
      <p className="mt-4 text-xs text-ink-400">
        Почему не готовый датасет с Kaggle: там размечена тональность новостей вообще, а не «важно ли это конкретной
        компании», и чаще на английском. Рыночная реакция и ваши оценки отвечают ровно на наш вопрос. Архив старых
        новостей (CSV или JSON) можно добавить командой <code>python -m scripts.import_history</code> — он разметится
        по рынку. Когда меток наберутся тысячи, вместо логистической регрессии можно дообучить компактную
        русскоязычную модель (например, ruBERT).
      </p>
    </Modal>
  );
}
