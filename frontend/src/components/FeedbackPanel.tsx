import { GraduationCap } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import type { EventDetail, Feedback } from "../types";

type Answer = Omit<Feedback, "updated_at">;
const EMPTY: Answer = { relevant: null, impact_type: null, priority: null };

function Choice<T extends string | boolean>({ label, value, options, onPick, disabled }: {
  label: string;
  value: T | null;
  options: { v: T; text: string; tone?: string }[];
  onPick: (v: T | null) => void;
  disabled: boolean;
}) {
  return (
    <div>
      <div className="mb-1 text-xs text-ink-500">{label}</div>
      <div className="flex flex-wrap gap-0.5 rounded-lg border border-ink-200 bg-white p-0.5">
        {options.map((o) => {
          const on = value === o.v;
          return (
            <button key={String(o.v)} type="button" disabled={disabled}
              // повторный клик снимает ответ
              onClick={() => onPick(on ? null : o.v)}
              className={`flex-auto whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium transition ${
                on ? o.tone || "bg-ink-900 text-white" : "text-ink-700 hover:bg-ink-100"}`}
              aria-pressed={on}>
              {o.text}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// оценка разбора пользователем: на этих оценках обучается своя модель (см. backend/app/model.py)
export default function FeedbackPanel({ ev }: { ev: EventDetail }) {
  const { profileId, status, reloadStatus, bumpData, toast } = useApp();
  const [answer, setAnswer] = useState<Answer>(ev.feedback || EMPTY);
  const [busy, setBusy] = useState(false);

  useEffect(() => setAnswer(ev.feedback || EMPTY), [ev.id, ev.feedback?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = async (next: Answer) => {
    setAnswer(next);
    setBusy(true);
    try {
      const res = await api.sendFeedback(profileId, ev.id, next);
      const m = res.model;
      if (!res.feedback) toast("Оценка снята");
      else if (m.trained) toast(`Оценка учтена. Модель переобучена на ${m.labels.relevance} оценках`);
      else toast(`Оценка сохранена. До обучения модели: ещё ${Math.max(0, m.min_labels - m.labels.relevance)} (нужны и «да», и «нет»)`);
      await reloadStatus();
      bumpData();
    } catch (e: any) {
      setAnswer(ev.feedback || EMPTY);
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const model = status?.model;
  const p = ev.ml?.p_relevant;

  return (
    <div className="card p-5">
      <div className="flex items-center gap-2">
        <GraduationCap size={17} className="text-ink-500" />
        <h2 className="section-title">Оцените разбор</h2>
      </div>
      <p className="mt-1 text-xs text-ink-500">На ваших оценках учится своя модель сервиса и поправляет баллы похожих новостей.</p>

      <div className="mt-4 space-y-3">
        <Choice label="Относится к компании?" value={answer.relevant} disabled={busy}
          options={[{ v: true, text: "Да" }, { v: false, text: "Нет" }]}
          onPick={(v) => send({ ...answer, relevant: v })} />
        <Choice label="Для компании это" value={answer.impact_type} disabled={busy}
          options={[
            { v: "risk", text: "Риск", tone: "bg-rose-600 text-white" },
            { v: "opportunity", text: "Возможность", tone: "bg-emerald-600 text-white" },
            { v: "neutral", text: "Нейтрально" },
          ]}
          onPick={(v) => send({ ...answer, impact_type: v })} />
        <Choice label="Важность определена" value={answer.priority} disabled={busy}
          options={[{ v: "lower", text: "Завышена" }, { v: "ok", text: "Верно" }, { v: "higher", text: "Занижена" }]}
          onPick={(v) => send({ ...answer, priority: v })} />
      </div>

      {ev.market && (
        <div className="mt-4 rounded-lg border border-ink-200 px-3 py-2 text-xs leading-relaxed text-ink-700">
          <b>Реакция рынка:</b> акции {ev.market.ticker} за {ev.market.horizon} торговых дня после новости{" "}
          <span className={ev.market.ar < 0 ? "font-semibold text-rose-700" : "font-semibold text-emerald-700"}>
            {ev.market.ar > 0 ? "+" : ""}{ev.market.ar}%
          </span>{" "}к индексу Мосбиржи (z = {ev.market.z}).{" "}
          {ev.market.relevant === true ? "Это значимая реакция — метка «относится» для обучения модели."
            : ev.market.relevant === false ? "Рынок новость не заметил."
            : "Реакция неоднозначная — в обучение не идёт."}
        </div>
      )}
      <div className="mt-4 rounded-lg bg-ink-50 px-3 py-2 text-xs leading-relaxed text-ink-700">
        {model?.active && p !== undefined ? (
          <>Своя модель: вероятность, что событие значимо для компании, — <b>{Math.round(p * 100)}%</b>.
            Релевантность по правилам {ev.rules_relevance}, итоговая {ev.relevance} (вес модели {Math.round((ev.ml.weight || 0) * 100)}%).</>
        ) : model?.trained && !model.enabled ? (
          <>Своя модель обучена, но выключена — баллы считают только правила.</>
        ) : (
          <>Модель пока не обучена: нужно {model?.min_labels ?? 6} оценок «относится / не относится» (сейчас {model?.labels ?? 0})
            или рыночная разметка по публичным компаниям. Пока баллы считают правила.</>
        )}
      </div>
    </div>
  );
}
