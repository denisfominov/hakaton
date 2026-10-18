import { Building2, ChevronDown, ClipboardCheck, Cpu, LayoutDashboard, Newspaper, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../context";

const NAV = [
  { to: "/", label: "Обзор", icon: LayoutDashboard, end: true },
  { to: "/feed", label: "Лента событий", icon: Newspaper },
  { to: "/decisions", label: "Решения", icon: ClipboardCheck },
  { to: "/profile", label: "Профиль компании", icon: Building2 },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white">A</div>
      <div className="leading-tight">
        <div className="text-sm font-semibold">Alpha Intelligence</div>
        <div className="text-[11px] text-ink-500">новостная аналитика для бизнеса</div>
      </div>
    </div>
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
  if (!status) return null;
  return (
    <span className="hidden items-center gap-1 rounded-md bg-ink-100 px-2 py-1 text-xs text-ink-500 lg:inline-flex"
      title={status.llm.note || `Модель: ${status.llm.model}`}>
      <Cpu size={12} />
      {status.llm.enabled ? `Правила + LLM (${status.llm.model})` : "Аналитика: правила"}
    </span>
  );
}

function RefreshMenu() {
  const { status, reloadStatus, bumpData, toast } = useApp();
  const realDataset = status?.dataset !== "synthetic";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const run = async (mode: "dataset" | "live") => {
    setOpen(false);
    setBusy(true);
    try {
      const res = await api.refresh(mode);
      if (mode === "dataset") {
        toast(realDataset ? "Подборка реальных новостей перезагружена из файла"
          : "Синтетический набор перезагружен, даты пересчитаны от текущего момента");
      } else {
        const ok = res.report.filter((r) => r.ok);
        const failed = res.report.filter((r) => !r.ok && !r.skipped);
        const added = ok.reduce((s, r) => s + (r.added || 0), 0);
        if (!ok.length) toast(res.message || "Источники недоступны", "error");
        else toast(`Загружено новых событий: ${added}. Источников ответило: ${ok.length}` +
          (failed.length ? `, с ошибкой: ${failed.map((f) => f.source).join(", ")}` : ""));
      }
      await reloadStatus();
      bumpData();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button className="btn-secondary" onClick={() => setOpen((o) => !o)} disabled={busy}>
        <RefreshCw size={15} className={busy ? "animate-spin" : ""} />
        <span className="hidden sm:inline">{busy ? "Обновляем…" : "Обновить ленту"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-72 rounded-xl border border-ink-200 bg-white p-1.5 shadow-lg">
          <button className="w-full rounded-lg px-3 py-2 text-left hover:bg-ink-50" onClick={() => run("live")}>
            <div className="text-sm font-medium">Загрузить свежие новости из RSS</div>
            <div className="text-xs text-ink-500">Банк России, Интерфакс, РБК, Коммерсантъ</div>
          </button>
          <button className="w-full rounded-lg px-3 py-2 text-left hover:bg-ink-50" onClick={() => run("dataset")}>
            <div className="text-sm font-medium">{realDataset ? "Перезагрузить подборку" : "Перезагрузить синтетический набор"}</div>
            <div className="text-xs text-ink-500">
              {realDataset ? "Реальные публикации о 5 компаниях со ссылками на оригиналы" : "Вымышленные события для тестов и показа"}
            </div>
          </button>
        </div>
      )}
    </div>
  );
}

function ProfileSwitcher() {
  const { profiles, profileId, setProfileId, bumpData } = useApp();
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Building2 size={16} className="hidden shrink-0 text-ink-400 sm:block" />
      <select
        className="input !w-auto min-w-0 max-w-[220px] !py-1.5 font-medium sm:max-w-[320px]"
        value={profileId}
        onChange={(e) => {
          setProfileId(e.target.value);
          bumpData();
        }}
        aria-label="Профиль компании"
      >
        {profiles.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
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
              <Icon size={17} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto rounded-lg bg-ink-50 p-3 text-xs leading-relaxed text-ink-500">
          MVP для хакатона. Данные хранятся локально, без авторизации пользователей.
        </div>
      </aside>

      <header className="sticky top-0 z-20 border-b border-ink-200 bg-white/90 backdrop-blur">
        <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
          <div className="md:hidden">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white">A</div>
          </div>
          <ProfileSwitcher />
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
