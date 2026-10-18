import { useState } from "react";
import type { FormEvent } from "react";
import type { Action } from "../types";

export type ActionDraft = Pick<Action, "title" | "description" | "priority" | "due_date" | "owner" | "comment"> & {
  status?: Action["status"];
};

interface Props {
  initial: ActionDraft;
  withStatus?: boolean;
  submitLabel: string;
  onSubmit: (d: ActionDraft) => Promise<void>;
  onCancel: () => void;
}

export default function ActionForm({ initial, withStatus, submitLabel, onSubmit, onCancel }: Props) {
  const [d, setD] = useState<ActionDraft>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof ActionDraft>(k: K, v: ActionDraft[K]) => setD((prev) => ({ ...prev, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (d.title.trim().length < 3) {
      setError("Название должно быть не короче 3 символов");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit(d);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label className="label" htmlFor="a-title">Название</label>
        <input id="a-title" className="input" value={d.title} onChange={(e) => set("title", e.target.value)} autoFocus />
      </div>
      <div>
        <label className="label" htmlFor="a-desc">Описание</label>
        <textarea id="a-desc" className="input min-h-[90px]" value={d.description} onChange={(e) => set("description", e.target.value)} />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label className="label" htmlFor="a-prio">Приоритет</label>
          <select id="a-prio" className="input" value={d.priority} onChange={(e) => set("priority", e.target.value as ActionDraft["priority"])}>
            <option value="high">Высокий</option>
            <option value="medium">Средний</option>
            <option value="low">Низкий</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="a-due">Срок</label>
          <input id="a-due" type="date" className="input" value={d.due_date || ""} onChange={(e) => set("due_date", e.target.value || null)} />
        </div>
        {withStatus ? (
          <div>
            <label className="label" htmlFor="a-status">Статус</label>
            <select id="a-status" className="input" value={d.status} onChange={(e) => set("status", e.target.value as Action["status"])}>
              <option value="new">Новое</option>
              <option value="in_progress">В работе</option>
              <option value="done">Выполнено</option>
            </select>
          </div>
        ) : (
          <div>
            <label className="label" htmlFor="a-owner">Ответственный</label>
            <input id="a-owner" className="input" value={d.owner} onChange={(e) => set("owner", e.target.value)} />
          </div>
        )}
      </div>
      {withStatus && (
        <div>
          <label className="label" htmlFor="a-owner2">Ответственный</label>
          <input id="a-owner2" className="input" value={d.owner} onChange={(e) => set("owner", e.target.value)} />
        </div>
      )}
      <div>
        <label className="label" htmlFor="a-comment">Комментарий</label>
        <textarea id="a-comment" className="input min-h-[70px]" value={d.comment} placeholder="Например: согласовать с финансовым директором"
          onChange={(e) => set("comment", e.target.value)} />
      </div>
      {error && <p className="text-sm text-red-700">{error}</p>}
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className="btn-secondary" onClick={onCancel}>Отмена</button>
        <button type="submit" className="btn-primary" disabled={saving}>{saving ? "Сохраняем…" : submitLabel}</button>
      </div>
    </form>
  );
}
