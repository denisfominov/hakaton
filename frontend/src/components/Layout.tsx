import {
  Briefcase, Building2, Check, ChevronDown, ClipboardCheck, Cpu, LayoutDashboard, Newspaper, RefreshCw, ShieldCheck,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";
import { plural, timeAgo } from "../utils";
import AnalyticsPanel from "./AnalyticsPanel";
import SourcesModal from "./SourcesModal";

const NAV = [
  { to: "/companies", label: "Выбор компании", icon: Briefcase, end: false },
  { to: "/", label: "Обзор", icon: LayoutDashboard, end: true },
  { to: "/feed", label: "Лента событий", icon: Newspaper },
  { to: "/decisions", label: "Решения", icon: ClipboardCheck },
  { to: "/profile", label: "Профиль компании", icon: Building2 },
];

function Logo() {
  return (
    <Link to="/about" className="-m-1.5 flex items-center gap-2.5 rounded-lg p-1.5 transition hover:bg-ink-50" title="О сервисе">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white">A</div>
      <div className="leading-tight">
        <div className="text-sm font-semibold">Alpha Intelligence</div>
        <div className="text-[11px] text-ink-500">новостная аналитика · о сервисе</div>
      </div>
    </Link>
  );
}

function DataModeBadge() {
  const { status } = useApp();
  if (!status) return null;
  const builtin = status.dataset === "real" ? "подборка" : "синтетика";
  const map = {
    curated: { text: "Реальные новости · подборка", cls: "bg-sky-50 text-sky-800 ring-sky-200",
      tip: "Подборка реальных публикаций о компаниях из профилей: ссылки на оригиналы, текст — краткий пересказ командой." },
    synthetic: { text: "Синтетические данные", cls: "bg-violet-50 text-violet-700 ring-violet-200",
      tip: "Вымышленные компании и события (режим DATASET=synthetic). Помечены «Демо»." },
    live: { text: "Свежие RSS", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", tip: "Показаны новости из RSS" },
    mixed: { text: `RSS + ${builtin}`, cls: "bg-amber-50 text-amber-800 ring-amber-200",
      tip: `Подборка: ${status.events.curated + status.events.demo}, RSS: ${status.events.live}. Фильтр источника — в ленте.` },
  }[status.data_mode];
  return (
    <span className={`hidden rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset md:inline-block ${map.cls}`} title={map.tip}>
      {map.text}
    </span>
  );
}

function EngineBadge() {
  const { status } = useApp();
  const [open, setOpen] = useState(false);
  if (!status) return null;
  const parts = ["Правила"];
  if (status.model?.active) parts.push("своя модель");
  if (status.llm.enabled) parts.push("LLM");
  const text = parts.length > 1 ? `Аналитика: ${parts.join(" + ")}` : "Аналитика: правила";
  const tip = status.model?.active
    ? `Своя модель обучена на ${status.model.labels} оценках. Нажмите, чтобы посмотреть подробности`
    : `Своя модель копит оценки (${status.model?.labels ?? 0} из ${status.model?.min_labels ?? 6}). Нажмите, чтобы узнать, как устроена аналитика`;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title={tip}
        aria-label={text}
        className="inline-flex items-center gap-1 rounded-md bg-ink-100 px-2 py-1.5 text-xs text-ink-700 transition hover:bg-ink-200 lg:py-1">
        <Cpu size={12} />
        <span className="hidden lg:inline">{text}</span>
        {status.model?.active && <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-emerald-500" />}
      </button>
      {open && <AnalyticsPanel onClose={() => setOpen(false)} />}
    </>
  );
}

function RefreshMenu() {
  const { status, profiles, reloadStatus, bumpData, toast } = useApp();
  const realDataset = status?.dataset !== "synthetic";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const feeds = (status?.sources || []).filter((s) => s.enabled);
  const ru = feeds.filter((s) => s.country === "RU").length;
  const foreign = feeds.length - ru;
  const builtin = (status?.events.curated || 0) + (status?.events.demo || 0);
  const live = status?.events.live || 0;
  const last = status?.live.last;
  const companies = status?.companies ?? profiles.length;

  const run = async (mode: "dataset" | "live") => {
    setOpen(false);
    setBusy(true);
    try {
      const res = await api.refresh(mode);
      if (mode === "dataset") {
        toast(realDataset ? `Подборка перезагружена: ${builtin} публикаций, анализ для ${companies} ${plural(companies, "компании", "компаний", "компаний")}`
          : "Синтетический набор перезагружен, даты пересчитаны от текущего момента");
      } else {
        const ok = res.report.filter((r) => r.ok);
        const failed = res.report.filter((r) => !r.ok && !r.skipped);
        const ruAdded = ok.filter((r) => r.country === "RU").reduce((s, r) => s + (r.added || 0), 0);
        const frAdded = ok.filter((r) => r.country && r.country !== "RU").reduce((s, r) => s + (r.added || 0), 0);
        if (!ok.length) toast(res.message || "Источники недоступны", "error");
        else toast(`Новых: ${ruAdded} из российских и ${frAdded} из зарубежных изданий. Ответило ${ok.length} из ${ok.length + failed.length}` +
          (failed.length ? ` (не ответили: ${failed.map((f) => f.source).join(", ")})` : ""));
      }
      await reloadStatus();
      bumpData();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const Row = ({ on, children }: { on: boolean; children: ReactNode }) => (
    <div className="flex items-start gap-2 text-xs">
      <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${on ? "bg-emerald-600 text-white" : "bg-ink-200 text-ink-400"}`}>
        {on && <Check size={11} />}
      </span>
      <span className={on ? "text-ink-900" : "text-ink-500"}>{children}</span>
    </div>
  );

  return (
    <div className="relative" ref={ref}>
      <button className="btn-secondary" onClick={() => setOpen((o) => !o)} disabled={busy}>
        <RefreshCw size={15} className={busy ? "animate-spin" : ""} />
        <span className="hidden sm:inline">{busy ? "Обновляем…" : "Новости"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] rounded-xl border border-ink-200 bg-white p-1.5 shadow-lg">
          <div className="space-y-1.5 rounded-lg bg-ink-50 px-3 py-2.5">
            <div className="text-[11px] font-medium uppercase tracking-wide text-ink-500">Сейчас в ленте</div>
            <Row on={builtin > 0}>
              {realDataset ? "Проверенная подборка" : "Синтетический набор"}: {builtin} {plural(builtin, "публикация", "публикации", "публикаций")}
            </Row>
            <Row on={live > 0}>
              Свежие новости из RSS: {live > 0
                ? <>{live} из {status?.live.outlets} изданий{last ? <> · загружены {timeAgo(last.ts)}</> : null}</>
                : "ещё не загружались"}
            </Row>
            <div className="pt-0.5 text-[11px] text-ink-500">
              Анализ — для {companies} {plural(companies, "компании", "компаний", "компаний")} из «Выбора компании». Источник в ленте можно выбрать фильтром.
            </div>
          </div>
          <button className="mt-1 w-full rounded-lg px-3 py-2 text-left hover:bg-ink-50" onClick={() => run("live")}>
            <div className="text-sm font-medium">Загрузить свежие новости</div>
            <div className="text-xs text-ink-500">
              {feeds.length} {plural(feeds.length, "издание", "издания", "изданий")}: {ru} российских и {foreign} зарубежных
              (доля зарубежных — не больше 10%). Одна новость в разных изданиях склеивается и получает выше достоверность.
            </div>
          </button>
          <button className="w-full rounded-lg px-3 py-2 text-left hover:bg-ink-50" onClick={() => run("dataset")}>
            <div className="text-sm font-medium">{realDataset ? "Перезагрузить проверенную подборку" : "Перезагрузить синтетический набор"}</div>
            <div className="text-xs text-ink-500">
              {realDataset ? `${status?.events.curated || 0} публикаций со ссылками на оригиналы, проверены вручную`
                : "Вымышленные события для тестов и показа"}
            </div>
          </button>
          <button className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-ink-50"
            onClick={() => { setOpen(false); setShowSources(true); }}>
            <ShieldCheck size={15} className="mt-0.5 shrink-0 text-ink-500" />
            <span>
              <span className="block text-sm font-medium">Источники и их репутация</span>
              <span className="block text-xs text-ink-500">Как считается достоверность новости</span>
            </span>
          </button>
        </div>
      )}
      {showSources && <SourcesModal onClose={() => setShowSources(false)} />}
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { profile } = useApp();
  return (
    <div className="min-h-screen md:pl-60">
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-ink-200 bg-white px-4 py-5 md:flex">
        <Logo />
        <nav className="mt-8 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-ink-100"}`}>
              <Icon size={17} className="shrink-0" />
              <span className="min-w-0">
                {label}
                {to === "/companies" && profile && (
                  <span className="block truncate text-[11px] font-normal opacity-70">{profile.name}</span>
                )}
              </span>
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto rounded-lg bg-ink-50 p-3 text-xs leading-relaxed text-ink-500">
          MVP для хакатона. Данные хранятся локально, без авторизации пользователей.
        </div>
      </aside>

      <header className="sticky top-0 z-20 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
          <Link to="/about" className="flex min-w-0 items-center gap-2 md:hidden" title="О сервисе">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white">A</span>
            {profile && <span className="truncate text-sm font-medium text-ink-700">{profile.name}</span>}
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <EngineBadge />
            <DataModeBadge />
            <RefreshMenu />
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-2 md:hidden">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-ink-900 text-white" : "text-ink-700"}`}>
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}
