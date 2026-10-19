import { ExternalLink, Layers, ShieldAlert, Star } from "lucide-react";
import { Link } from "react-router-dom";
import type { EventCard as EventCardT } from "../types";
import { timeAgo } from "../utils";
import { DemoBadge, ImpactBadge, Meter, PriorityScore, UrgencyBadge, VerificationBadge } from "./Badges";

interface Props {
  ev: EventCardT;
  onToggleFavorite?: (id: string) => void;
}

export default function EventCard({ ev, onToggleFavorite }: Props) {
  return (
    <article className="card group p-4 transition hover:border-ink-300 sm:p-5">
      <div className="flex gap-4">
        <div className="hidden shrink-0 sm:block">
          <PriorityScore value={ev.priority} level={ev.priority_level} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-500">
            {ev.is_demo && <DemoBadge />}
            <span className="font-medium text-ink-700">{ev.category_label}</span>
            <span>·</span>
            <span className="truncate">{ev.source}</span>
            <span>·</span>
            <span title={new Date(ev.published_at).toLocaleString("ru-RU")}>{timeAgo(ev.published_at)}</span>
            {ev.related_count > 0 && (
              <span className="inline-flex items-center gap-1 text-ink-500" title="Похожие публикации объединены в одно событие">
                <Layers size={12} /> +{ev.related_count} публ.
              </span>
            )}
          </div>

          <Link to={`/events/${ev.id}`} className="mt-1.5 block text-base font-semibold leading-snug text-ink-900 hover:text-brand-dark">
            <span className="mr-2 inline-block align-middle sm:hidden">
              <span className="rounded bg-ink-900 px-1.5 py-0.5 text-xs text-white tabular-nums">{ev.priority}</span>
            </span>
            {ev.title}
          </Link>
          {ev.summary && <p className="mt-1 line-clamp-2 text-sm text-ink-500">{ev.summary}</p>}

          <div className="mt-3 rounded-lg bg-ink-50 px-3 py-2 text-sm">
            <span className="font-medium text-ink-700">Почему важно: </span>
            <span className="text-ink-700">{ev.summary_line}</span>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <ImpactBadge type={ev.impact_type} />
            <UrgencyBadge level={ev.urgency_level} />
            <VerificationBadge v={ev.verification} status={ev.fact_status} />
            {ev.suspicious && (
              <span className="inline-flex items-center gap-1 text-xs text-red-700" title="В тексте найдены инструкции для ИИ — проигнорированы">
                <ShieldAlert size={12} /> текст с инструкциями
              </span>
            )}
          </div>

          <div className="mt-3 flex flex-wrap items-end gap-x-6 gap-y-2">
            <Meter label="Релевантность" value={ev.relevance} tone="brand" />
            <Meter label="Влияние" value={ev.impact} />
            <Meter label="Уверенность" value={ev.confidence} />
            <div className="ml-auto flex items-center gap-1">
              {ev.url ? (
                <a href={ev.url} target="_blank" rel="noreferrer" className="btn-ghost !px-2 !py-1 text-xs">
                  <ExternalLink size={14} /> Оригинал
                </a>
              ) : (
                <span className="px-2 text-xs text-ink-400" title="У демонстрационных событий нет оригинала">без ссылки</span>
              )}
              {onToggleFavorite && (
                <button
                  className={`btn-ghost !px-2 !py-1 ${ev.favorite ? "text-amber-500 hover:text-amber-600" : ""}`}
                  onClick={() => onToggleFavorite(ev.id)}
                  aria-label={ev.favorite ? "Убрать из избранного" : "В избранное"}
                  title={ev.favorite ? "Убрать из избранного" : "В избранное"}
                >
                  <Star size={16} fill={ev.favorite ? "currentColor" : "none"} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}
