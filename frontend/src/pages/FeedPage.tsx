import { Search, Star, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import EventCard from "../components/EventCard";
import { Empty, ErrorBox, Skeleton } from "../components/States";
import { useApp, useLoad } from "../context";
import { plural } from "../utils";

const DEFAULTS = { q: "", days: "", category: "", impact: "", level: "", mode: "", ver: "", fav: "", all: "", sort: "priority" };
type FilterKey = keyof typeof DEFAULTS;

// ниже этой релевантности новость почти не связана с компанией; в живых RSS таких большинство
const MIN_RELEVANCE = 20;

export default function FeedPage() {
  const { profileId, dataVersion, meta, status, toast } = useApp();
  const [params, setParams] = useSearchParams();
  const get = (k: FilterKey) => params.get(k) ?? DEFAULTS[k];
  const [search, setSearch] = useState(get("q"));

  const set = (k: FilterKey, v: string) => {
    const next = new URLSearchParams(params);
    if (!v || v === DEFAULTS[k]) next.delete(k);
    else next.set(k, v);
    setParams(next, { replace: true });
  };

  // поиск применяем с небольшой задержкой, чтобы не дёргать API на каждую букву
  useEffect(() => {
    const t = setTimeout(() => {
      if (search !== get("q")) set("q", search);
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const filters = {
    q: get("q"),
    days: Number(get("days")) || undefined,
    min_verification: Number(get("ver")) || undefined,
    category: get("category"),
    impact: get("impact"),
    level: get("level"),
    mode: get("mode"),
    favorites_only: get("fav") === "1",
    sort: get("sort"),
    min_relevance: get("all") === "1" ? 0 : MIN_RELEVANCE,
  };

  const { data, setData, loading, error, reload } = useLoad(
    () => api.events(profileId, filters),
    [profileId, params.toString(), dataVersion],
  );

  const toggleFavorite = async (id: string) => {
    try {
      const res = await api.toggleFavorite(profileId, id);
      if (!data) return;
      if (filters.favorites_only && !res.favorite) {
        setData({ total: data.total - 1, items: data.items.filter((e) => e.id !== id) });
      } else {
        setData({ ...data, items: data.items.map((e) => (e.id === id ? { ...e, favorite: res.favorite } : e)) });
      }
      toast(res.favorite ? "Добавлено в избранное" : "Убрано из избранного");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const activeFilters = (["days", "category", "impact", "level", "mode", "ver", "fav", "all", "q"] as FilterKey[]).filter((k) => get(k));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Лента событий</h1>
        <p className="mt-1 text-sm text-ink-500">Новости как бизнес-события: оценка для выбранной компании, риски, возможности и уверенность</p>
      </div>

      <div className="card space-y-3 p-3 sm:p-4">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className="input !pl-9" placeholder="Поиск по заголовкам и тексту: тарифы, субстанции, Китай…"
            value={search} onChange={(e) => setSearch(e.target.value)} />
          {search && (
            <button className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-400 hover:text-ink-700"
              onClick={() => setSearch("")} aria-label="Очистить поиск"><X size={14} /></button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="input !w-auto !py-1.5" value={get("days")} onChange={(e) => set("days", e.target.value)} aria-label="Период">
            <option value="">За всё время</option>
            <option value="1">24 часа</option>
            <option value="7">7 дней</option>
            <option value="30">30 дней</option>
            <option value="90">90 дней</option>
          </select>
          <select className="input !w-auto !py-1.5" value={get("category")} onChange={(e) => set("category", e.target.value)} aria-label="Категория">
            <option value="">Все категории</option>
            {meta?.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
          <select className="input !w-auto !py-1.5" value={get("impact")} onChange={(e) => set("impact", e.target.value)} aria-label="Тип влияния">
            <option value="">Любой тип</option>
            <option value="risk">Риски</option>
            <option value="opportunity">Возможности</option>
            <option value="neutral">Нейтральные</option>
          </select>
          <select className="input !w-auto !py-1.5" value={get("level")} onChange={(e) => set("level", e.target.value)} aria-label="Важность">
            <option value="">Любая важность</option>
            <option value="critical">Критическая</option>
            <option value="high">Высокая и выше</option>
            <option value="medium">Средняя и выше</option>
          </select>
          <select className="input !w-auto !py-1.5" value={get("mode")} onChange={(e) => set("mode", e.target.value)} aria-label="Источник данных">
            <option value="">Все источники</option>
            {status?.dataset !== "synthetic" && <option value="curated">Подборка реальных новостей</option>}
            <option value="live">Свежие RSS</option>
            {!!status?.events.demo && <option value="demo">Синтетика</option>}
          </select>
          <select className="input !w-auto !py-1.5" value={get("ver")} onChange={(e) => set("ver", e.target.value)} aria-label="Достоверность">
            <option value="">Любая достоверность</option>
            <option value="60">Средняя и выше</option>
            <option value="80">Только высокая</option>
          </select>
          <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-ink-700"
            title={`Скрывать события с релевантностью ниже ${MIN_RELEVANCE} — они почти не связаны с компанией`}>
            <input type="checkbox" className="h-4 w-4 accent-ink-900" checked={get("all") !== "1"}
              onChange={(e) => set("all", e.target.checked ? "" : "1")} />
            Только значимые для компании
          </label>
          <button className={`btn-secondary !py-1.5 ${get("fav") ? "!border-amber-300 !bg-amber-50 !text-amber-700" : ""}`}
            onClick={() => set("fav", get("fav") ? "" : "1")}>
            <Star size={14} fill={get("fav") ? "currentColor" : "none"} /> Избранное
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-ink-500">Сортировка</span>
            <select className="input !w-auto !py-1.5" value={get("sort")} onChange={(e) => set("sort", e.target.value)} aria-label="Сортировка">
              <option value="priority">По приоритету</option>
              <option value="urgency">По срочности</option>
              <option value="relevance">По релевантности</option>
              <option value="confidence">По уверенности</option>
              <option value="verification">По достоверности</option>
              <option value="date">Сначала новые</option>
            </select>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-ink-500">
        <span>
          {data ? `Найдено ${data.total} ${plural(data.total, "событие", "события", "событий")}` : " "}
        </span>
        {activeFilters.length > 0 && (
          <button className="btn-ghost !py-1" onClick={() => { setSearch(""); setParams({}, { replace: true }); }}>
            Сбросить фильтры
          </button>
        )}
      </div>

      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Skeleton rows={4} />}
      {data && data.items.length === 0 && (
        <Empty
          title={filters.favorites_only ? "В избранном пока пусто" : "Ничего не найдено"}
          text={filters.favorites_only ? "Отмечайте звёздочкой события, к которым хотите вернуться." :
            filters.mode === "live" ? "Свежих новостей из RSS ещё нет — загрузите их через «Обновить ленту»." :
              filters.min_relevance ? "Попробуйте ослабить фильтры или снимите галочку «Только значимые для компании»." :
                "Попробуйте изменить запрос или ослабить фильтры."}
        />
      )}
      {data && data.items.length > 0 && (
        <div className={`space-y-3 ${loading ? "opacity-60" : ""}`}>
          {data.items.map((ev) => <EventCard key={ev.id} ev={ev} onToggleFavorite={toggleFavorite} />)}
        </div>
      )}
    </div>
  );
}
