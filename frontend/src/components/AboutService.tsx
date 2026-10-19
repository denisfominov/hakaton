import { ChevronDown, ChevronUp, Compass } from "lucide-react";
import { useState } from "react";

const KEY = "alpha.aboutCollapsed";

function readCollapsed() {
  try {
    // sessionStorage: в новой сессии справка снова открыта
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

// короткая справка на обзоре: что за сервис, зачем он и куда смотреть. Не зависит от выбранной компании
export default function AboutService() {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      sessionStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      // приватный режим — просто не запоминаем
    }
  };

  if (collapsed) {
    return (
      <button onClick={toggle} className="flex w-full items-center gap-2 rounded-xl border border-ink-200 bg-white px-4 py-2.5 text-left text-sm text-ink-700 hover:bg-ink-50">
        <Compass size={16} className="text-ink-500" />
        <span className="flex-1">Что это за сервис и как им пользоваться</span>
        <ChevronDown size={16} className="text-ink-400" />
      </button>
    );
  }

  return (
    <section className="rounded-xl border border-ink-200 bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Compass size={18} className="text-ink-500" />
          <h2 className="font-semibold">Alpha Intelligence — новости, переведённые в решения</h2>
        </div>
        <button onClick={toggle} className="btn-ghost !px-2 !py-1 text-xs" aria-label="Свернуть справку">
          Свернуть <ChevronUp size={14} />
        </button>
      </div>
      <div className="mt-4 grid gap-5 text-sm text-ink-700 md:grid-cols-3">
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-ink-500">Что это</h3>
          <p className="mt-1.5">
            Сервис читает поток деловых новостей и для выбранной компании отвечает: что произошло, почему это важно
            именно ей, риск это или возможность, насколько срочно и что делать.
          </p>
        </div>
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-ink-500">Зачем</h3>
          <p className="mt-1.5">
            Чтобы руководитель не читал сотни новостей. Сервис отбирает значимые для его бизнеса, объясняет связь с
            компанией и предлагает действия: почему они важны, что даст их выполнение и чем грозит бездействие.
          </p>
        </div>
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-ink-500">Как пользоваться</h3>
          <ol className="mt-1.5 list-decimal space-y-1 pl-4">
            <li>Слева «Выбор компании» — выберите компанию или добавьте свою по сайту или ИНН, проверьте профиль.</li>
            <li>Здесь, на обзоре, — что требует реакции и главные события за период.</li>
            <li>Откройте событие: разбор, балл и рекомендуемые действия. Нужные добавьте в план («Решения»).</li>
            <li>Оцените разбор — сервис учится на ваших оценках.</li>
          </ol>
        </div>
      </div>
      <div className="mt-4 rounded-lg bg-ink-50 px-4 py-3 text-sm text-ink-700">
        <b>Куда смотреть в первую очередь:</b> карточки «Критические риски» и «Требуют реакции»; список «Требует
        внимания в первую очередь». Число в квадрате — приоритет для компании от 0 до 100 (70 и выше — критический),
        метки «Риск» и «Возможность» — тип влияния. Пометка «Один источник» значит, что факт стоит перепроверить.
      </div>
    </section>
  );
}
