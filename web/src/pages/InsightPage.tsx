import { useEffect, useState } from "react";
import { getCard, getTrace, type ClaimView, type InsightCard, type SourceView, type Trace } from "../api";
import { loadSelection } from "../selection";
import { texts } from "../texts";

const t = texts.card;
const date = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
const number = new Intl.NumberFormat("ru-RU");
const PROVENANCES = ["fact", "bank", "model", "hypothesis"];

type Load = { kind: "loading" } | { kind: "ok"; card: InsightCard } | { kind: "error"; message: string };
type TraceLoad = { kind: "hidden" } | { kind: "loading" } | { kind: "ok"; trace: Trace } | { kind: "missing" };

function Provenance({ value, confidence }: { value: string; confidence?: number | null }) {
  return (
    <span className={`tag prov-${value}`} title={t.provenanceHint[value]}>
      {t.provenance[value] ?? value}
      {value === "hypothesis" && confidence != null && ` · ${Math.round(confidence * 100)}%`}
    </span>
  );
}

function bankSource(ref: string) {
  const [documentId, page] = ref.split(":");
  const title = texts.bankDocuments[documentId] ?? documentId;
  return page?.startsWith("p") ? `${title}, ${t.page(page.slice(1))}` : title;
}

function Source({ source }: { source: SourceView }) {
  const kind = t.sourceKinds[source.kind] ?? source.kind;
  const label = source.kind === "alfa_analytics" ? bankSource(source.ref)
    : source.title ?? (source.kind === "news" || source.kind === "event_analysis" ? "" : source.ref);
  return (
    <li title={source.quote ?? undefined}>
      <span className="muted">{kind}{label ? ": " : ""}</span>
      {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{label || source.url}</a> : label}
      {source.kind === "alfa_analytics" && source.quote && <q className="quote">{source.quote}</q>}
    </li>
  );
}

function Claim({ claim }: { claim: ClaimView }) {
  return (
    <li className="card-claim">
      <div>
        <Provenance value={claim.provenance} confidence={claim.confidence} />
        <span>{claim.text}</span>
      </div>
      {claim.sources.length > 0 && <ul className="sources">{claim.sources.map((s, i) => <Source key={i} source={s} />)}</ul>}
    </li>
  );
}

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
                        {n.url ? <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a> : n.title}
                      </li>
                    ))}
                  </ul>
                </>
              )}
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
                  ? <ul className="card-claims">{card.sections[section].map((c, i) => <Claim key={i} claim={c} />)}</ul>
                  : <p className="muted">{section === "bank_view" ? t.noBankView : t.emptySection}</p>}
              </section>
            ))}

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
