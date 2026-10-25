import { Icon, type IconName } from "../components/Icon";
import { texts } from "../texts";

const actions: { icon: IconName; label: string }[] = [
  { icon: "download", label: texts.actions.statement },
  { icon: "upload", label: texts.actions.importPayments },
  { icon: "plus", label: texts.actions.createPayment },
];

export function HomePage({ onOpenInsights }: { onOpenInsights: () => void }) {
  const { balance, tasks, promo, requests, conversion } = texts;
  return (
    <div className="content">
      <div className="actions">
        {actions.map((action) => (
          <button key={action.label} className="action">
            <Icon name={action.icon} size={18} />
            {action.label}
          </button>
        ))}
        <button className="action action-muted">{texts.actions.more}</button>
      </div>

      <section className="insights-banner">
        <span className="insights-banner-icon"><Icon name="insight" size={28} /></span>
        <div>
          <h2>{texts.insightsBanner.title}</h2>
          <p>{texts.insightsBanner.text}</p>
        </div>
        <button className="insights-banner-button" onClick={onOpenInsights}>
          {texts.insightsBanner.button}
          <Icon name="chevron" size={18} />
        </button>
      </section>

      <section className="hero">
        <div className="hero-balance">
          <span className="muted">{balance.caption}</span>
          <strong className="hero-total">{balance.total}</strong>
          <span className="muted">↳ {balance.overdraft}</span>
          <div className="hero-currencies">
            {balance.currencies.map((c) => <span key={c}>{c}</span>)}
            <span className="pill">{balance.moreCurrencies}</span>
          </div>
          <div className="hero-links">
            <div><Icon name="account" /><b>{balance.accounts}</b><span className="muted">{balance.accountsHint}</span></div>
            <div><Icon name="card" /><b>{balance.cards}</b><span className="muted">{balance.cardsHint}</span></div>
          </div>
        </div>
        <div className="hero-tasks">
          <h3>{tasks.title}</h3>
          {tasks.items.map((task) => (
            <div key={task.label} className="task">
              <span>{task.label}</span>
              <span className={`count ${task.alert ? "count-alert" : ""}`}>{task.count}</span>
            </div>
          ))}
        </div>
        <div className="hero-promo">
          <h3>{promo.title}</h3>
          <p className="muted">{promo.text}</p>
        </div>
        <div className="hero-footer">
          <span>{balance.details}</span>
          <span>{balance.tariff}</span>
        </div>
      </section>

      <nav className="tabs">
        {texts.tabs.map((tab, i) => <span key={tab} className={i === 0 ? "tab active" : "tab"}>{tab}</span>)}
      </nav>

      <div className="widgets">
        <section className="widget">
          <h3>{requests.title} <span className="pill">{requests.items.length}</span></h3>
          {requests.items.map((r) => (
            <div key={r.name} className="request">
              <b>{r.name}</b>
              <div className="request-row"><span>{r.amount}</span><span className="status-pill">{r.status}</span></div>
              <span className="muted small">{r.meta}</span>
            </div>
          ))}
        </section>
        <section className="widget">
          <h3>{conversion.title}</h3>
          <table>
            <thead><tr>{conversion.head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{conversion.rows.map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
