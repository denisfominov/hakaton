import { ArrowRight, Briefcase, ClipboardCheck, Compass, Cpu, LayoutDashboard, Newspaper, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import SourcesModal from "../components/SourcesModal";
import { useApp } from "../context";

function Step({ n, icon: Icon, title, to, children }: {
  n: number; icon: typeof Compass; title: string; to: string; children: ReactNode;
}) {
  return (
    <li className="card flex gap-3 p-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink-900 text-xs font-semibold text-white">{n}</span>
      <div className="min-w-0">
        <Link to={to} className="inline-flex items-center gap-1.5 font-medium hover:underline">
          <Icon size={15} className="text-ink-500" /> {title} <ArrowRight size={13} className="text-ink-400" />
        </Link>
        <p className="mt-1 text-sm text-ink-700">{children}</p>
      </div>
    </li>
  );
}

// «О сервисе»: что это, зачем, как пользоваться и куда смотреть. Открывается по клику на логотип
export default function AboutPage() {
  const { status } = useApp();
  const [sources, setSources] = useState(false);
  const feeds = (status?.sources || []).filter((s) => s.enabled);
  const ru = feeds.filter((s) => s.country === "RU").length;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-ink-500"><Compass size={16} /> О сервисе</div>
        <h1 className="mt-1 text-2xl font-semibold">Alpha Intelligence — новости, переведённые в решения</h1>
      </div>

      <section className="grid gap-5 text-sm text-ink-700 md:grid-cols-2">
        <div className="card p-5">
          <h2 className="text-xs font-medium uppercase tracking-wide text-ink-500">Что это</h2>
          <p className="mt-2">
            Сервис читает поток деловых новостей и для выбранной компании отвечает: что произошло, почему это важно
            именно ей, риск это или возможность, насколько срочно и что делать.
          </p>
        </div>
        <div className="card p-5">
          <h2 className="text-xs font-medium uppercase tracking-wide text-ink-500">Зачем</h2>
          <p className="mt-2">
            Чтобы руководитель не читал сотни новостей. Сервис отбирает значимые для его бизнеса, объясняет связь с
            компанией и предлагает действия: почему они важны, что даст их выполнение и чем грозит бездействие.
          </p>
        </div>
      </section>

      <section>
        <h2 className="section-title">Как пользоваться</h2>
        <ol className="mt-3 grid gap-3 md:grid-cols-2">
          <Step n={1} icon={Briefcase} title="Выбор компании" to="/companies">
            Выберите компанию или добавьте свою по сайту или ИНН: сервис соберёт данные из ЕГРЮЛ, порталов проверки
            контрагентов, сайта компании и Википедии и заполнит профиль. Проверьте и поправьте его.
          </Step>
          <Step n={2} icon={LayoutDashboard} title="Обзор" to="/">
            Что требует реакции и главные события за период. Столбцы динамики кликабельны — откроют новости дня.
          </Step>
          <Step n={3} icon={Newspaper} title="Лента и разбор события" to="/feed">
            В разборе — связь с компанией, риски и возможности, балл 0–100 и из чего он сложился, достоверность
            и рекомендуемые действия.
          </Step>
          <Step n={4} icon={ClipboardCheck} title="Решения" to="/decisions">
            Нужные действия добавьте в план: ответственный, срок, статус. Оцените разбор — сервис учится на оценках.
          </Step>
        </ol>
      </section>

      <section className="rounded-xl border border-ink-200 bg-white p-5 text-sm text-ink-700">
        <h2 className="section-title">Куда смотреть в первую очередь</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Карточки «Критические риски» и «Требуют реакции» на обзоре и список «Требует внимания в первую очередь».</li>
          <li>Число в квадрате — приоритет для компании от 0 до 100: 70 и выше — критический, 50–69 — высокий.</li>
          <li>Метки «Риск» и «Возможность» — тип влияния; срочность — как быстро нужна реакция.</li>
          <li>Достоверность: «Высокая» — надёжное издание и подтверждения в других; «Низкая» — проверьте первоисточник.</li>
        </ul>
      </section>

      <section className="grid gap-5 text-sm text-ink-700 md:grid-cols-2">
        <div className="card p-5">
          <h2 className="flex items-center gap-2 section-title"><ShieldCheck size={15} className="text-ink-500" /> Откуда новости</h2>
          <p className="mt-2">
            Проверенная подборка публикаций со ссылками и свежие новости {feeds.length} изданий по RSS: {ru} российских
            и {feeds.length - ru} зарубежных (не больше 10% ленты). Одинаковые новости из разных изданий склеиваются в
            одно событие, достоверность растёт с репутацией изданий и числом независимых подтверждений.
          </p>
          <button className="btn-secondary mt-3 !py-1.5 text-xs" onClick={() => setSources(true)}>Источники и их репутация</button>
        </div>
        <div className="card p-5">
          <h2 className="flex items-center gap-2 section-title"><Cpu size={15} className="text-ink-500" /> Как считается</h2>
          <p className="mt-2">
            Правила по профилю компании находят каналы влияния и считают баллы; своя модель учится на оценках
            пользователей и на реакции акций публичных компаний; LLM по кнопке только переписывает разбор понятным
            языком. Подробности — по кнопке «Аналитика» вверху.
          </p>
        </div>
      </section>
      {sources && <SourcesModal onClose={() => setSources(false)} />}
    </div>
  );
}
