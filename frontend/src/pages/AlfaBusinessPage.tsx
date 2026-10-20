import { ArrowRight, Building2, CreditCard, Info, Newspaper, Sparkles, Wallet } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ImpactBadge } from "../components/Badges";
import { ErrorBox, Skeleton } from "../components/States";
import { useApp, useLoad } from "../context";

// заглушка раздела интернет-банка: в макете не подключено, данных нет — ничего не выдаём за настоящие счета
function Placeholder({ icon: Icon, title }: { icon: typeof Wallet; title: string }) {
  return (
    <div className="card flex items-center gap-3 border-dashed p-4 text-ink-400">
      <Icon size={20} />
      <div>
        <div className="text-sm font-medium text-ink-500">{title}</div>
        <div className="text-xs">в макете не подключено</div>
      </div>
    </div>
  );
}

// макет главного экрана интернет-банка Альфа-Бизнес с заметной точкой входа в сервис (кейс, критерий 08)
export default function AlfaBusinessPage() {
  const { profiles, profileId, profile, setProfileId, bumpData } = useApp();
  const navigate = useNavigate();
  const { data, loading, error, reload } = useLoad(
    () => api.events(profileId, { sort: "priority", limit: 3, min_relevance: 20 }), [profileId]);

  const open = (to: string) => {
    bumpData();
    navigate(to);
  };

  return (
    <div className="space-y-5">
      <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
        <Info size={14} className="mt-0.5 shrink-0" />
        <p>Демо-макет главного экрана интернет-банка для показа точки входа. Интеграции с банком нет: счета, платежи и вход —
          заглушки; лента и аналитика ниже — настоящие данные сервиса.</p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="shrink-0">
          <div className="whitespace-nowrap text-xs font-medium uppercase tracking-wide text-rose-600">Альфа-Бизнес · макет</div>
          <h1 className="text-2xl font-semibold">Главная</h1>
        </div>
        <label className="flex min-w-0 items-center gap-2 text-sm text-ink-600">
          <Building2 size={15} />
          <select className="input !w-auto max-w-[18rem] !py-1.5" value={profileId} onChange={(e) => { setProfileId(e.target.value); bumpData(); }}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>

      {/* точка входа: заметная, на главном экране, всегда видна */}
      <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-rose-600 to-rose-700 text-white shadow-sm">
        <div className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-rose-100"><Sparkles size={16} /> Новости и аналитика для вашего бизнеса</div>
            <p className="mt-1 text-lg font-semibold">Что из новостей важно {profile ? `для ${profile.name}` : "вашей компании"} и как это оценивает банк</p>
          </div>
          <button className="inline-flex items-center gap-1.5 self-start rounded-lg bg-white px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 sm:self-auto"
            onClick={() => open("/")}>
            Открыть аналитику <ArrowRight size={15} />
          </button>
        </div>
        <div className="bg-white/10 px-5 pb-5">
          {error && <ErrorBox error={error} onRetry={reload} />}
          {loading && !data && <div className="pt-4"><Skeleton rows={2} /></div>}
          {data && data.items.length === 0 && <p className="pt-4 text-sm text-rose-100">Значимых событий для компании сейчас нет.</p>}
          <ul className="divide-y divide-white/15">
            {data?.items.map((e) => (
              <li key={e.id} className="py-3">
                <button className="group w-full text-left" onClick={() => open(`/events/${e.id}`)}>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-white/90 px-1.5 text-xs font-semibold tabular-nums text-rose-700">{e.priority}</span>
                    <ImpactBadge type={e.impact_type} />
                  </div>
                  <div className="mt-1 font-medium group-hover:underline">{e.title}</div>
                  <div className="text-sm text-rose-100">{e.summary_line}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-3">
        <Placeholder icon={Wallet} title="Счета и остатки" />
        <Placeholder icon={CreditCard} title="Платежи" />
        <Placeholder icon={Newspaper} title="Кредиты и гарантии" />
      </div>

      <Link to="/" className="fixed bottom-5 right-5 z-20 inline-flex items-center gap-2 rounded-full bg-rose-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-rose-700">
        <Sparkles size={16} /> Новостная аналитика
      </Link>
    </div>
  );
}
