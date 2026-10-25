import { useEffect, useState } from "react";
import { getProfile, getReference, type Claim, type CompanyProfile, type Sensitivity } from "../api";
import { count, rubles } from "../format";
import { claim, factorLabel, gap, paymentRoles, reason, roleBasis, titleCase } from "../profileText";
import { texts } from "../texts";

const percent = (value: number | null) => (value === null ? texts.noData : `${Math.round(value * 100)}%`);
const MEMBERS_SHOWN = 10;
const FACTORS_SHOWN = 10;

type Load = { kind: "loading" } | { kind: "ok"; profile: CompanyProfile } | { kind: "error"; message: string };

function ProvenanceTag({ provenance, confidence }: { provenance: string; confidence?: number | null }) {
  const hypothesis = provenance === "hypothesis";
  return (
    <span className={hypothesis ? "tag tag-hypothesis" : "tag tag-fact"}>
      {hypothesis ? texts.profile.hypothesis : texts.profile.fact}
      {hypothesis && confidence != null && ` · ${texts.profile.confidence(percent(confidence))}`}
    </span>
  );
}

function FactorRow({ item, industry }: { item: Sensitivity; industry: (key: string) => string }) {
  return (
    <li className="factor">
      <div className="factor-head">
        <span className="factor-name">{factorLabel(item.factor, { industry })}</span>
        <span className="tag">{texts.profile.scope[item.scope] ?? item.scope}</span>
        {item.provenance === "hypothesis" && <ProvenanceTag provenance={item.provenance} />}
      </div>
      <div className="bar"><span style={{ width: `${Math.round(item.weight * 100)}%` }} /></div>
      <ul className="reasons">
        {item.reasons.map((r) => <li key={r}>{reason(r, { industry })}</li>)}
      </ul>
    </li>
  );
}

function ClaimRow({ item, industry }: { item: Claim; industry: (key: string) => string }) {
  return (
    <li className="claim">
      <ProvenanceTag provenance={item.provenance} confidence={item.confidence} />
      <span>{claim(item.text, { industry })}</span>
    </li>
  );
}

export function ProfileView({ companyId }: { companyId: string }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [industries, setIndustries] = useState<Record<string, string>>({});
  const [allFactors, setAllFactors] = useState(false);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    getProfile(companyId)
      .then((profile) => active && setLoad({ kind: "ok", profile }))
      .catch((error: Error) => active && setLoad({ kind: "error", message: error.message }));
    return () => {
      active = false;
    };
  }, [companyId]);

  useEffect(() => {
    getReference()
      .then((reference) => setIndustries(Object.fromEntries(reference.industries.map((i) => [i.industry, i.name]))))
      .catch(() => setIndustries({}));
  }, []);

  if (load.kind === "loading") return <p className="muted">{texts.profile.loading}</p>;
  if (load.kind === "error") return <p className="error-text">{texts.profile.error}: {load.message}</p>;

  const p = load.profile;
  const industry = (key: string) => industries[key] ?? key;
  const factors = [...p.sensitivities].sort((a, b) => b.weight - a.weight);
  const shownFactors = allFactors ? factors : factors.slice(0, FACTORS_SHOWN);
  const t = texts.profile;

  return (
    <div className="profile">
      <section className="widget profile-head">
        <div>
          <h3>{p.uid} · {p.industry_label ?? industry(p.industry ?? "")}</h3>
          <p><span className="code">{p.okved_code ?? "—"}</span> {p.okved_name ?? texts.noData}</p>
          <p className="muted">{[p.region, p.city].filter(Boolean).join(", ")}</p>
          <div className="chips">
            {p.client_type && <span className="tag">{t.clientTypes[p.client_type] ?? p.client_type}</span>}
            {p.is_large && <span className="tag tag-fact">{t.large}</span>}
          </div>
        </div>
        <div className="numbers">
          <div><span className="muted">{t.revenue}</span><b>{rubles(p.revenue)}</b></div>
          <div><span className="muted">{t.groupRevenue}</span><b>{rubles(p.group_revenue)}</b></div>
        </div>
      </section>

      <div className="profile-grid">
        <section className="widget">
          <h3>{t.products}</h3>
          <div className="chips">
            {p.products.length ? p.products.map((x) => <span key={x} className="chip">{texts.products[x] ?? x}</span>)
              : <span className="muted">{t.noProducts}</span>}
          </div>
          {p.trade_countries.length > 0 && (
            <>
              <h3 className="sub">{t.countries}</h3>
              <div className="chips">{p.trade_countries.map((c) => <span key={c} className="chip">{titleCase(c)}</span>)}</div>
            </>
          )}
        </section>
        <section className="widget">
          <h3>{t.position}</h3>
          <ul className="plain">
            {p.positions.map((pos) => (
              <li key={pos.scope + pos.key}>
                <b>{pos.rank ? t.place(pos.rank, count(pos.peers)) : texts.noData}</b> {t.positionScope[pos.scope] ?? pos.scope} {pos.key}
                {pos.revenue_share_in_sample !== null && <span className="muted"> · {t.sampleShare(percent(pos.revenue_share_in_sample))}</span>}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="widget">
        <h3>{t.features}</h3>
        <table className="features">
          <tbody>
            {p.features.map((f) => (
              <tr key={f.name}>
                <td>{texts.featureNames[f.name] ?? f.name}</td>
                <td><b>{typeof f.value === "boolean" ? (f.value ? t.yes : t.no) : f.value ?? texts.noData}</b></td>
                <td className="muted small">{t.source}: <span className="code">{f.source.ref}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="widget">
        <h3>{t.factors}</h3>
        <p className="muted small">{t.factorsHint}</p>
        <ul className="factors">{shownFactors.map((s) => <FactorRow key={s.factor} item={s} industry={industry} />)}</ul>
        {factors.length > FACTORS_SHOWN && (
          <button className="action link" onClick={() => setAllFactors(!allFactors)}>
            {allFactors ? t.showLess : t.showAll(factors.length)}
          </button>
        )}
      </section>

      {p.group && (
        <section className="widget">
          <h3>{t.group} <span className="code">{p.group.group_id}</span></h3>
          <p>{t.groupSize(p.group.size, p.group.clients)} · {rubles(p.group.revenue)}</p>
          <h3 className="sub">{t.groupIndustries}</h3>
          <ul className="shares">
            {p.group.industries.map((i) => (
              <li key={i.industry}>
                <span>{i.label ?? industry(i.industry)}</span>
                <div className="bar"><span style={{ width: `${Math.round(i.share * 100)}%` }} /></div>
                <b>{percent(i.share)}</b>
              </li>
            ))}
          </ul>
          <h3 className="sub">{t.groupRegions}</h3>
          <div className="chips">{p.group.regions.map((r) => <span key={r} className="chip">{r}</span>)}</div>
          {p.group.members.length > 0 && (
            <>
              <h3 className="sub">{t.members}</h3>
              <table className="companies-table">
                <thead><tr>{t.memberColumns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>
                  {p.group.members.slice(0, MEMBERS_SHOWN).map((m) => (
                    <tr key={m.uid} className={m.uid === p.uid ? "current" : ""}>
                      <td><b>{m.uid}</b>{m.is_client && <span className="tag">{t.client}</span>}</td>
                      <td><span className="code">{m.okved_code ?? "—"}</span></td>
                      <td>{m.region ?? texts.noData}</td>
                      <td className="number">{percent(m.revenue_share)}</td>
                      <td>
                        {texts.roles[m.role] ?? m.role}
                        {paymentRoles.has(m.role) && <> <ProvenanceTag provenance="hypothesis" /></>}
                        <div className="muted small">{roleBasis(m.role_basis)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}

      {p.hypotheses.length > 0 && (
        <section className="widget">
          <h3>{t.hypotheses}</h3>
          <p className="muted small">{t.hypothesesHint}</p>
          <ul className="claims">{p.hypotheses.map((c) => <ClaimRow key={c.text} item={c} industry={industry} />)}</ul>
        </section>
      )}

      {p.data_gaps.length > 0 && (
        <section className="widget">
          <h3>{t.gaps}</h3>
          <ul className="plain">{p.data_gaps.map((g) => <li key={g}>{gap(g)}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
