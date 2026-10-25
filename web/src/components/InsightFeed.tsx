import { useCallback, useEffect, useRef, useState } from "react";
import { getCards, getJob, getReference, startAnalysis, type InsightCard, type Job } from "../api";
import { factorLabel } from "../profileText";
import type { Role } from "../selection";
import { texts } from "../texts";

const POLL_MS = 3000;
const NO_KEY = "LLM_API_KEY";

const failure = (message: string | null) => (message?.includes(NO_KEY) ? texts.feed.noKey : message ?? "");
const date = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

type Load = { kind: "loading" } | { kind: "ok"; cards: InsightCard[] } | { kind: "error"; message: string };
type Run = { kind: "idle" } | { kind: "job"; job: Job } | { kind: "error"; message: string };

function CardItem({ card, industry }: { card: InsightCard; industry: (key: string) => string }) {
  const t = texts.feed;
  return (
    <li className="insight-card" role="link" tabIndex={0}
      onClick={() => (window.location.hash = `#/insight/${card.id}`)}
      onKeyDown={(e) => e.key === "Enter" && (window.location.hash = `#/insight/${card.id}`)}>
      <div className="insight-meta">
        <span className={`tag impact-${card.impact}`}>{t.impact[card.impact] ?? card.impact}</span>
        <span className="tag">{t.relevance(`${Math.round(card.relevance * 100)}%`)}</span>
        {card.has_bank_view && <span className="tag tag-bank">{t.bankView}</span>}
        <span className="muted small">
          {card.published_at ? date.format(new Date(card.published_at)) : ""}
          {card.news.length > 0 && ` · ${card.news.map((n) => n.source).filter((v, i, a) => a.indexOf(v) === i).join(", ")}`}
        </span>
      </div>
      <h4>{card.title}</h4>
      {card.headline && <p className="insight-headline">{card.headline}</p>}
      {card.role_focus.length > 0 && (
        <div className="chips">
          <span className="muted small">{t.focus}:</span>
          {card.role_focus.map((f) => <span key={f} className="chip">{factorLabel(f, { industry })}</span>)}
        </div>
      )}
    </li>
  );
}

export function InsightFeed({ companyId, role }: { companyId: string; role: Role }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [run, setRun] = useState<Run>({ kind: "idle" });
  const [industries, setIndustries] = useState<Record<string, string>>({});
  const timer = useRef<number | undefined>(undefined);

  const reload = useCallback(() => {
    setLoad({ kind: "loading" });
    getCards(companyId, role)
      .then((cards) => setLoad({ kind: "ok", cards }))
      .catch((error: Error) => setLoad({ kind: "error", message: error.message }));
  }, [companyId, role]);

  useEffect(reload, [reload]);

  useEffect(() => {
    getReference()
      .then((reference) => setIndustries(Object.fromEntries(reference.industries.map((i) => [i.industry, i.name]))))
      .catch(() => setIndustries({}));
    return () => window.clearTimeout(timer.current);
  }, []);

  const poll = (jobId: string) => {
    timer.current = window.setTimeout(() => {
      getJob(jobId)
        .then((job) => {
          setRun({ kind: "job", job });
          if (job.status === "done") reload();
          else if (job.status !== "failed") poll(jobId);
        })
        .catch((error: Error) => setRun({ kind: "error", message: error.message }));
    }, POLL_MS);
  };

  const analyze = () => {
    startAnalysis(companyId)
      .then((job) => {
        setRun({ kind: "job", job });
        poll(job.id);
      })
      .catch((error: Error) => setRun({ kind: "error", message: error.message }));
  };

  const t = texts.feed;
  const busy = run.kind === "job" && (run.job.status === "queued" || run.job.status === "running");
  const industry = (key: string) => industries[key] ?? key;

  return (
    <section className="widget feed">
      <div className="feed-head">
        <div>
          <h3>{t.title(texts.picker.roles[role])}</h3>
          <p className="muted small">{t.hint}</p>
        </div>
        <button className="action action-primary" disabled={busy} onClick={analyze}>{t.refresh}</button>
      </div>
      <p className="muted small">{t.refreshHint}</p>
      {run.kind === "job" && (
        <p className={run.job.status === "failed" ? "error-text" : "status-line"}>
          {run.job.status === "queued" && t.queued}
          {run.job.status === "running" && t.running}
          {run.job.status === "done" && t.done(run.job.results.filter((r) => r.insight_id).length)}
          {run.job.status === "failed" && `${t.failed}: ${failure(run.job.error)}`}
        </p>
      )}
      {run.kind === "error" && <p className="error-text">{t.failed}: {failure(run.message)}</p>}

      {load.kind === "loading" && <p className="muted">{t.loading}</p>}
      {load.kind === "error" && <p className="error-text">{t.error}: {load.message}</p>}
      {load.kind === "ok" && load.cards.length === 0 && <p className="muted">{t.empty}</p>}
      {load.kind === "ok" && load.cards.length > 0 && (
        <ul className="insight-list">{load.cards.map((c) => <CardItem key={c.id} card={c} industry={industry} />)}</ul>
      )}
    </section>
  );
}
