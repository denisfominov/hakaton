import type { ReactNode } from "react";
import { texts } from "../texts";
import { Icon, type IconName } from "./Icon";
import { ServerStatus } from "./ServerStatus";

export type Page = "home" | "insights";

const menu: { icon: IconName; label: string; badge?: string }[] = [
  { icon: "request", label: texts.menu.requests, badge: texts.newBadge },
  { icon: "plus", label: texts.menu.newPayment },
  { icon: "feed", label: texts.menu.operations },
  { icon: "clock", label: texts.menu.paymentsInWork },
  { icon: "upload", label: texts.menu.importRegistry },
  { icon: "statement", label: texts.menu.statement },
  { icon: "account", label: texts.menu.accounts },
  { icon: "people", label: texts.menu.counterparties },
  { icon: "certificate", label: texts.menu.certificates },
  { icon: "invoice", label: texts.menu.invoices },
  { icon: "card", label: texts.menu.cards },
];

type Props = { page: Page; onNavigate: (page: Page) => void; children: ReactNode };

export function Shell({ page, onNavigate, children }: Props) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => onNavigate("home")}>
          <span className="brand-logo">А</span>
          <span>{texts.brand}</span>
        </button>
        <a className="menu-item">
          <Icon name="grid" />
          {texts.allServices}
        </a>
        <hr />
        <button className={`menu-item menu-insights ${page === "insights" ? "active" : ""}`}
          onClick={() => onNavigate("insights")}>
          <Icon name="insight" />
          {texts.menu.insights}
          <span className="badge badge-ai">{texts.aiBadge}</span>
        </button>
        {menu.map((item) => (
          <a key={item.label} className="menu-item">
            <Icon name={item.icon} />
            {item.label}
            {item.badge && <span className="badge badge-new">{item.badge}</span>}
          </a>
        ))}
        <hr />
        <a className="menu-item">
          <Icon name="tender" />
          {texts.menu.tenders}
        </a>
        <a className="menu-item menu-bottom">
          <Icon name="settings" />
          {texts.customizeMenu}
        </a>
      </aside>
      <div className="main">
        <header className="topbar">
          <ServerStatus />
          <span className="topbar-icon"><Icon name="mail" /></span>
          <span className="topbar-icon"><Icon name="bell" /></span>
          <div className="companies">
            <strong>{texts.myCompanies}</strong>
            <span>{texts.userName}</span>
          </div>
          <span className="boss">{texts.boss}</span>
        </header>
        {children}
      </div>
    </div>
  );
}
