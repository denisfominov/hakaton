import type { ClaimView, SourceView } from "../api";
import { texts } from "../texts";

const t = texts.card;

export type OpenSource = (url: string) => void;

export function Provenance({ value, confidence }: { value: string; confidence?: number | null }) {
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

export function ExternalLink({ url, label, onOpen }: { url: string; label: string; onOpen?: OpenSource }) {
  return <a href={url} target="_blank" rel="noreferrer" onClick={() => onOpen?.(url)}>{label}</a>;
}

function Source({ source, onOpen }: { source: SourceView; onOpen?: OpenSource }) {
  const kind = t.sourceKinds[source.kind] ?? source.kind;
  const label = source.kind === "alfa_analytics" ? bankSource(source.ref)
    : source.title ?? (source.kind === "news" || source.kind === "event_analysis" ? "" : source.ref);
  return (
    <li title={source.quote ?? undefined}>
      <span className="muted">{kind}{label ? ": " : ""}</span>
      {source.url ? <ExternalLink url={source.url} label={label || source.url} onOpen={onOpen} /> : label}
      {source.kind === "alfa_analytics" && source.quote && <q className="quote">{source.quote}</q>}
    </li>
  );
}

export function Claim({ claim, onOpen }: { claim: ClaimView; onOpen?: OpenSource }) {
  return (
    <li className="card-claim">
      <div>
        <Provenance value={claim.provenance} confidence={claim.confidence} />
        <span>{claim.text}</span>
      </div>
      {claim.sources.length > 0 && (
        <ul className="sources">{claim.sources.map((s, i) => <Source key={i} source={s} onOpen={onOpen} />)}</ul>
      )}
    </li>
  );
}
