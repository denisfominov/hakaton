import { Icon } from "../components/Icon";
import { texts } from "../texts";

export function InsightsPage({ onBack }: { onBack: () => void }) {
  return (
    <div className="content">
      <section className="widget insights-placeholder">
        <span className="insights-banner-icon"><Icon name="insight" size={28} /></span>
        <h2>{texts.insightsPage.title}</h2>
        <p className="muted">{texts.insightsPage.text}</p>
        <button className="action" onClick={onBack}>{texts.insightsPage.back}</button>
      </section>
    </div>
  );
}
