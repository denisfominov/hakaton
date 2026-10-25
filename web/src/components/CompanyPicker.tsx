import { useEffect, useState } from "react";
import { getCompanies, getReference, type CompanyFilter, type CompanyPage } from "../api";
import { count, rubles } from "../format";
import { roles, type Role } from "../selection";
import { texts } from "../texts";

const PAGE_SIZE = 20;

type Props = { role: Role; onRole: (role: Role) => void; onPick: (companyId: string) => void };

type Load = { kind: "loading" } | { kind: "ok"; page: CompanyPage } | { kind: "error"; message: string };

export function CompanyPicker({ role, onRole, onPick }: Props) {
  const [filter, setFilter] = useState<CompanyFilter>({ large: true, region: "", okved: "", limit: PAGE_SIZE, offset: 0 });
  const [okvedInput, setOkvedInput] = useState("");
  const [regions, setRegions] = useState<string[]>([]);
  const [load, setLoad] = useState<Load>({ kind: "loading" });

  useEffect(() => {
    getReference()
      .then((reference) => setRegions(reference.regions.map((r) => r.name)))
      .catch(() => setRegions([]));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setFilter((f) => (f.okved === okvedInput ? f : { ...f, okved: okvedInput, offset: 0 })), 400);
    return () => clearTimeout(timer);
  }, [okvedInput]);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    getCompanies(filter)
      .then((page) => active && setLoad({ kind: "ok", page }))
      .catch((error: Error) => active && setLoad({ kind: "error", message: error.message }));
    return () => {
      active = false;
    };
  }, [filter]);

  const update = (patch: Partial<CompanyFilter>) => setFilter((f) => ({ ...f, ...patch, offset: 0 }));
  const total = load.kind === "ok" ? load.page.total : 0;

  return (
    <div className="picker">
      <section className="widget">
        <h3>{texts.picker.roleTitle}</h3>
        <div className="segmented">
          {roles.map((r) => (
            <button key={r} className={r === role ? "segment active" : "segment"} onClick={() => onRole(r)}>
              {texts.picker.roles[r]}
            </button>
          ))}
        </div>
      </section>

      <section className="widget">
        <h3>{texts.picker.companyTitle}</h3>
        <div className="filters">
          <label className="checkbox">
            <input type="checkbox" checked={filter.large} onChange={(e) => update({ large: e.target.checked })} />
            {texts.picker.largeOnly}
          </label>
          <select value={filter.region} onChange={(e) => update({ region: e.target.value })}>
            <option value="">{texts.picker.allRegions}</option>
            {regions.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <input value={okvedInput} placeholder={texts.picker.okvedPlaceholder} onChange={(e) => setOkvedInput(e.target.value)} />
        </div>

        {load.kind === "loading" && <p className="muted">{texts.picker.loading}</p>}
        {load.kind === "error" && <p className="error-text">{texts.picker.error}: {load.message}</p>}
        {load.kind === "ok" && load.page.items.length === 0 && <p className="muted">{texts.picker.empty}</p>}
        {load.kind === "ok" && load.page.items.length > 0 && (
          <>
            <table className="companies-table">
              <thead><tr>{texts.picker.columns.map((c) => <th key={c}>{c}</th>)}<th /></tr></thead>
              <tbody>
                {load.page.items.map((c) => (
                  <tr key={c.SYNTHETIC_U} onClick={() => onPick(c.SYNTHETIC_U)}>
                    <td><b>{c.SYNTHETIC_U}</b><div className="muted small">{texts.picker.group} {c.GROUP_ID ?? texts.noData}</div></td>
                    <td><span className="code">{c.MAINOKVED_CODE ?? "—"}</span> {c.MAINOKVED_NAME ?? texts.noData}</td>
                    <td>{c.REGION ?? texts.noData}</td>
                    <td className="number">{rubles(c.REVENUE_COMPANY)}</td>
                    <td className="number">{rubles(c.GROUP_REVENUE)}</td>
                    <td><button className="choose">{texts.picker.choose}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pager">
              <span className="muted">
                {texts.picker.shown(filter.offset + 1, filter.offset + load.page.items.length, count(total))}
              </span>
              <button className="action" disabled={filter.offset === 0}
                onClick={() => setFilter((f) => ({ ...f, offset: Math.max(0, f.offset - PAGE_SIZE) }))}>
                {texts.picker.previous}
              </button>
              <button className="action" disabled={filter.offset + PAGE_SIZE >= total}
                onClick={() => setFilter((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))}>
                {texts.picker.next}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
