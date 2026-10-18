import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function Loading({ text = "Загружаем данные…" }: { text?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-500">
      <Loader2 size={18} className="animate-spin" />
      {text}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="card animate-pulse p-4">
          <div className="h-3 w-1/3 rounded bg-ink-100" />
          <div className="mt-3 h-4 w-3/4 rounded bg-ink-100" />
          <div className="mt-2 h-3 w-2/3 rounded bg-ink-100" />
        </div>
      ))}
    </div>
  );
}

export function Empty({ title, text, action }: { title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      <Inbox className="text-ink-300" size={32} />
      <p className="mt-3 font-medium text-ink-700">{title}</p>
      {text && <p className="mt-1 max-w-md text-sm text-ink-500">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <AlertCircle size={18} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <p className="font-medium">Не удалось загрузить данные</p>
        <p className="mt-0.5">{error}</p>
      </div>
      {onRetry && (
        <button className="btn-secondary !py-1" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}
