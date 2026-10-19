import { CalendarClock, History, Link2, MessageSquare, Plus, User } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ActionForm from "../components/ActionForm";
import type { ActionDraft } from "../components/ActionForm";
import Modal from "../components/Modal";
import { Empty, ErrorBox, Loading, Skeleton } from "../components/States";
import { useApp, useLoad } from "../context";
import type { Action } from "../types";
import { PRIORITY_LABEL, STATUS_LABEL, formatDate, isOverdue } from "../utils";

const COLUMNS: { status: Action["status"]; title: string; dot: string }[] = [
  { status: "new", title: "Новые", dot: "bg-sky-500" },
  { status: "in_progress", title: "В работе", dot: "bg-amber-500" },
  { status: "done", title: "Выполнено", dot: "bg-emerald-500" },
];

const prioCls = { high: "bg-red-50 text-red-700", medium: "bg-amber-50 text-amber-800", low: "bg-ink-100 text-ink-500" };

function HistoryList({ actionId }: { actionId: number }) {
  const { data, loading, error } = useLoad(() => api.actionHistory(actionId), [actionId]);
  if (loading) return <Loading text="Загружаем историю…" />;
  if (error) return <ErrorBox error={error} />;
  if (!data?.length) return <p className="text-sm text-ink-500">Изменений пока нет</p>;
  return (
    <ol className="relative space-y-3 border-l border-ink-200 pl-4">
      {data.map((h) => (
        <li key={h.id} className="text-sm">
          <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-ink-400" />
          <div className="text-xs text-ink-400">{formatDate(h.ts)}</div>
          {h.what === "created" ? (
            <div>Действие создано</div>
          ) : (
            <div>
              <span className="font-medium">{h.what_label}:</span>{" "}
              <span className="text-ink-400 line-through">{fmtValue(h.what, h.old_value) || "пусто"}</span>{" "}
              → <span>{fmtValue(h.what, h.new_value) || "пусто"}</span>
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

function fmtValue(field: string, v: string | null) {
  if (!v) return "";
  if (field === "status") return STATUS_LABEL[v] || v;
  if (field === "priority") return PRIORITY_LABEL[v] || v;
  if (field === "due_date") return formatDate(v, false);
  return v.length > 80 ? v.slice(0, 80) + "…" : v;
}

function ActionCard({ a, onStatus, onOpen }: { a: Action; onStatus: (s: Action["status"]) => void; onOpen: () => void }) {
  const overdue = isOverdue(a.due_date, a.status);
  return (
    <div className="card p-4">
      <button className="block w-full text-left" onClick={onOpen}>
        <div className="flex items-start justify-between gap-2">
          <span className={`font-medium leading-snug ${a.status === "done" ? "text-ink-500 line-through" : ""}`}>{a.title}</span>
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${prioCls[a.priority]}`}>{PRIORITY_LABEL[a.priority]}</span>
        </div>
        {a.description && <p className="mt-1 line-clamp-2 text-sm text-ink-500">{a.description}</p>}
        {a.if_ignored && (
          <p className="mt-1.5 line-clamp-2 text-xs text-rose-700">
            <span className="font-medium">Если оставить без внимания:</span> {a.if_ignored}
          </p>
        )}
      </button>
      <div className="mt-3 space-y-1 text-xs text-ink-500">
        {a.event_id && a.event_title && (
          <Link to={`/events/${a.event_id}`} className="flex items-center gap-1.5 hover:text-ink-900">
            <Link2 size={12} className="shrink-0" /> <span className="truncate">{a.event_title}</span>
          </Link>
        )}
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {a.due_date && (
            <span className={`inline-flex items-center gap-1 ${overdue ? "font-medium text-red-600" : ""}`}>
              <CalendarClock size={12} /> {overdue ? "просрочено, " : "до "}{formatDate(a.due_date, false)}
            </span>
          )}
          {a.owner && <span className="inline-flex items-center gap-1"><User size={12} /> {a.owner}</span>}
          {a.comment && <span className="inline-flex items-center gap-1" title={a.comment}><MessageSquare size={12} /> комментарий</span>}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <select className="input !py-1 text-xs" value={a.status} onChange={(e) => onStatus(e.target.value as Action["status"])}
          aria-label="Статус">
          <option value="new">Новое</option>
          <option value="in_progress">В работе</option>
          <option value="done">Выполнено</option>
        </select>
        <button className="btn-ghost !px-2 !py-1 text-xs" onClick={onOpen}><History size={13} /> Детали</button>
      </div>
    </div>
  );
}

export default function DecisionsPage() {
  const { profileId, profile, dataVersion, toast } = useApp();
  const { data, setData, loading, error, reload } = useLoad(() => api.actions(profileId), [profileId, dataVersion]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);

  const replace = (a: Action) => setData((data || []).map((x) => (x.id === a.id ? a : x)));

  const changeStatus = async (a: Action, status: Action["status"]) => {
    try {
      replace(await api.updateAction(a.id, { status }));
      toast(`Статус: ${STATUS_LABEL[status]}`);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const opened = data?.find((a) => a.id === openId) || null;

  const saveEdit = async (d: ActionDraft) => {
    if (!opened) return;
    replace(await api.updateAction(opened.id, d));
    setHistoryKey((k) => k + 1);
    toast("Изменения сохранены");
  };

  const create = async (d: ActionDraft) => {
    const a = await api.createAction({ ...d, profile_id: profileId });
    setData([a, ...(data || [])]);
    setCreating(false);
    toast("Действие создано");
  };

  const counts = COLUMNS.map((c) => (data || []).filter((a) => a.status === c.status).length);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Панель решений</h1>
          <p className="mt-1 text-sm text-ink-500">План действий по событиям для {profile?.name}</p>
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={15} /> Новое действие</button>
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton rows={2} />}

      {data && data.length === 0 && (
        <Empty title="План действий пуст"
          text="Откройте важное событие в ленте и нажмите «В план действий» у нужной рекомендации — или создайте действие вручную."
          action={<Link to="/feed" className="btn-secondary">Перейти к ленте</Link>} />
      )}

      {data && data.length > 0 && (
        <div className="grid gap-5 md:grid-cols-3">
          {COLUMNS.map((col, i) => (
            <section key={col.status} className="space-y-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <span className={`h-2 w-2 rounded-full ${col.dot}`} /> {col.title}
                <span className="font-normal text-ink-400">{counts[i]}</span>
              </h2>
              {data.filter((a) => a.status === col.status).map((a) => (
                <ActionCard key={a.id} a={a} onStatus={(s) => changeStatus(a, s)} onOpen={() => setOpenId(a.id)} />
              ))}
              {counts[i] === 0 && <div className="rounded-xl border border-dashed border-ink-200 p-4 text-center text-xs text-ink-400">Пусто</div>}
            </section>
          ))}
        </div>
      )}

      <p className="text-xs text-ink-400">
        Ограничение MVP: действия хранятся в локальной базе SQLite на сервере приложения, пользователей и прав доступа нет.
      </p>

      {opened && (
        <Modal title="Действие" onClose={() => setOpenId(null)} wide>
          <div className="grid gap-6 md:grid-cols-5">
            <div className="md:col-span-3">
              {opened.event_id && opened.event_title && (
                <Link to={`/events/${opened.event_id}`} className="mb-4 flex items-center gap-1.5 rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-700 hover:bg-ink-100">
                  <Link2 size={12} /> Связанное событие: {opened.event_title}
                </Link>
              )}
              <ActionForm
                key={opened.updated_at}
                initial={{ title: opened.title, description: opened.description || "", priority: opened.priority,
                  due_date: opened.due_date, owner: opened.owner || "", comment: opened.comment || "", status: opened.status,
                  why: opened.why || "", if_done: opened.if_done || "", if_ignored: opened.if_ignored || "" }}
                withStatus submitLabel="Сохранить" onSubmit={saveEdit} onCancel={() => setOpenId(null)} />
            </div>
            <div className="md:col-span-2">
              <h3 className="mb-3 text-sm font-semibold">История изменений</h3>
              <HistoryList key={historyKey} actionId={opened.id} />
            </div>
          </div>
        </Modal>
      )}

      {creating && (
        <Modal title="Новое действие" onClose={() => setCreating(false)}>
          <ActionForm initial={{ title: "", description: "", priority: "medium", due_date: null, owner: "", comment: "" }}
            submitLabel="Создать" onSubmit={create} onCancel={() => setCreating(false)} />
        </Modal>
      )}
    </div>
  );
}
