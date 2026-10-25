import { useState } from "react";
import { CompanyPicker } from "../components/CompanyPicker";
import { Icon } from "../components/Icon";
import { ProfileView } from "../components/ProfileView";
import { loadSelection, saveSelection, type Role, type Selection } from "../selection";
import { texts } from "../texts";

export function InsightsPage() {
  const [selection, setSelection] = useState<Selection | null>(loadSelection);
  const [role, setRole] = useState<Role>(selection?.role ?? "cfo");

  const choose = (next: Selection | null) => {
    saveSelection(next);
    setSelection(next);
  };

  return (
    <div className="content">
      <header className="page-header">
        <span className="insights-banner-icon page-icon"><Icon name="insight" size={26} /></span>
        <div>
          <h2>{texts.insightsPage.title}</h2>
          <p className="muted">{texts.insightsPage.text}</p>
        </div>
      </header>

      {selection ? (
        <>
          <section className="widget selected">
            <div>
              <span className="muted">{texts.selected.title}</span>
              <h3>{selection.companyId} · {texts.picker.roles[selection.role]}</h3>
              <p className="muted">{texts.selected.next}</p>
            </div>
            <button className="action" onClick={() => choose(null)}>{texts.selected.change}</button>
          </section>
          <ProfileView companyId={selection.companyId} />
        </>
      ) : (
        <CompanyPicker role={role} onRole={setRole} onPick={(companyId) => choose({ companyId, role })} />
      )}
    </div>
  );
}
