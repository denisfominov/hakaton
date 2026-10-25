import { useEffect, useState } from "react";
import { getCard, getTrace, sendFeedback, type InsightCard, type Trace } from "../api";
import { AskPanel } from "../components/AskPanel";
import { Claim, ExternalLink, Provenance } from "../components/Claims";
import { FeedbackBar } from "../components/FeedbackBar";
import { loadSelection } from "../selection";
import { texts } from "../texts";

const t = texts.card;
const date = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
const number = new Intl.NumberFormat("ru-RU");
const PROVENANCES = ["fact", "bank", "model", "hypothesis"];

type Load = { kind: "loading" } | { kind: "ok"; card: InsightCard } | { kind: "error"; message: string };
type TraceLoad = { kind: "hidden" } | { kind: "loading" } | { kind: "ok"; trace: Trace } | { kind: "missing" };

function stepName(name: string) {
  const retry = name.match(/^verify_after_rewrite_(\d+)$/);
  return retry ? t.traceRetry(retry[1]) : t.traceSteps[name] ?? name;
}

function TraceView({ trace }: { trace: Trace }) {
  const seconds = trace.steps.reduce((sum, s) => sum + (s.ms ?? 0), 0) / 1000;
  const tokens = trace.llm_calls.reduce((sum, c) => sum + (c.prompt_tokens ?? 0) + (c.completion_tokens ?? 0), 0);
  return (
    <>
      <p className="muted small">{t.traceTotal(trace.steps.length, seconds.toFixed(1), trace.llm_calls.length, number.format(tokens))}</p>
      <ol className="trace">
        {trace.steps.map((step, i) => (
          <li key={i} className={step.error ? "trace-error" : ""}>
            <span className="tag">{t.traceKinds[step.kind] ?? step.kind}</span>
            {stepName(step.name)}
            {step.ms != null && <span className="muted small"> · {(step.ms / 1000).toFixed(1)} с</span>}
            {step.error && <span className="error-text small"> · {t.traceError}: {step.error}</span>}
          </li>
        ))}
      </ol>
      {trace.llm_calls.length > 0 && (
        <ul className="plain small">
          {trace.llm_calls.map((call, i) => (
            <li key={i} className={call.ok ? "" : "error-text"}>
              <span className="code">{call.model}</span> · {stepName(call.purpose ?? call.role)} · {(call.ms / 1000).toFixed(1)} с
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function InsightPage({ insightId, onBack }: { insightId: string; onBack: () => void }) {
  const selection = loadSelection();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [trace, setTrace] = useState<TraceLoad>({ kind: "hidden" });
  const role = selection?.role ?? "cfo";

  useEffect(() => {
    let active = true;
    getCard(insightId, role)
      .then((card) => active && setLoad({ kind: "ok", card }))
      .catch((error: Error) => active && setLoad({ kind: "error", message: error.message }));
    return () => {
      active = false;
    };
  }, [insightId, role]);

  const openSource = (url: string) => {
    sendFeedback(insightId, "open_source", role, url).catch(() => undefined);
  };

  const toggleTrace = () => {
    if (trace.kind !== "hidden") return setTrace({ kind: "hidden" });
    setTrace({ kind: "loading" });
    getTrace(insightId).then((value) => setTrace({ kind: "ok", trace: value })).catch(() => setTrace({ kind: "missing" }));
  };

  return (
    <div className="content">
      <button className="action link" onClick={onBack}>{t.back}</button>
      {load.kind === "loading" && <p className="muted">{t.loading}</p>}
      {load.kind === "error" && <p className="error-text">{t.error}: {load.message}</p>}
      {load.kind === "ok" && (() => {
        const card = load.card;
        const order = card.sections_order.length ? card.sections_order : Object.keys(card.sections);
        return (
          <>
            <section className="widget">
              <div className="insight-meta">
                <span className={`tag impact-${card.impact}`}>{texts.feed.impact[card.impact] ?? card.impact}</span>
                <span className="tag">{texts.feed.relevance(`${Math.round(card.relevance * 100)}%`)}</span>
                {card.has_bank_view && <span className="tag tag-bank">{texts.feed.bankView}</span>}
                {card.published_at && <span className="muted small">{date.format(new Date(card.published_at))}</span>}
              </div>
              <h2 className="card-title">{card.title}</h2>
              {card.event_summary && <p><b>{t.summary}:</b> {card.event_summary}</p>}
              {card.impact_reason && <p><b>{t.impactReason}:</b> {card.impact_reason}</p>}
              {card.news.length > 0 && (
                <>
                  <h3 className="sub">{t.sourcesTitle}</h3>
                  <ul className="plain">
                    {card.news.map((n, i) => (
                      <li key={i}>
                        <span className="muted">{n.source}: </span>
                        {n.url ? <ExternalLink url={n.url} label={n.title} onOpen={openSource} /> : n.title}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <FeedbackBar insightId={card.id} role={role} counts={card.feedback} />
            </section>

            <section className="widget legend">
              <h3>{t.legend}</h3>
              <ul className="plain">
                {PROVENANCES.map((p) => <li key={p}><Provenance value={p} /> {t.provenanceHint[p]}</li>)}
              </ul>
            </section>

            {order.map((section) => (
              <section key={section} className={`widget card-section section-${section}`}>
                <h3>{t.sections[section] ?? section}</h3>
                {(card.sections[section] ?? []).length > 0
                  ? <ul className="card-claims">{card.sections[section].map((c, i) => <Claim key={i} claim={c} onOpen={openSource} />)}</ul>
                  : <p className="muted">{section === "bank_view" ? t.noBankView : t.emptySection}</p>}
              </section>
            ))}

            <AskPanel insightId={card.id} role={role} onOpen={openSource} />

            <section className="widget">
              <div className="feed-head">
                <h3>{t.trace}</h3>
                <button className="action" onClick={toggleTrace}>{trace.kind === "hidden" ? t.traceShow : t.traceHide}</button>
              </div>
              {trace.kind === "loading" && <p className="muted">{t.loading}</p>}
              {trace.kind === "missing" && <p className="muted">{t.traceMissing}</p>}
              {trace.kind === "ok" && <TraceView trace={trace.trace} />}
            </section>
          </>
        );
      })()}
    </div>
  );
}
