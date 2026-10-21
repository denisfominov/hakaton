import { Bot, Cpu } from "lucide-react";
import type { ReactNode } from "react";
import { useApp } from "../context";
import Modal from "./Modal";

function Layer({ icon: Icon, title, state, tone, children }: {
  icon: typeof Cpu; title: string; state: string; tone: string; children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-ink-200 p-4">
      <div className="flex items-center gap-2">
        <Icon size={16} className="text-ink-500" />
        <h3 className="flex-1 text-sm font-semibold">{title}</h3>
        <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${tone}`}>{state}</span>
      </div>
      <div className="mt-2 space-y-2 text-sm text-ink-700">{children}</div>
    </div>
  );
}

// что стоит за бейджем «Аналитика»: правила по профилю и LLM по кнопке
export default function AnalyticsPanel({ onClose }: { onClose: () => void }) {
  const { status } = useApp();

  return (
    <Modal title="Как устроена аналитика" onClose={onClose} wide>
      <p className="text-sm text-ink-700">
        Сервис не пересылает новости в чужую модель «как есть». Значимость считают правила, и каждый балл можно
        разложить на причины.
      </p>
      <div className="mt-4 space-y-3">
        <Layer icon={Cpu} title="1. Правила по профилю компании" state="Работают всегда" tone="bg-emerald-50 text-emerald-700">
          <p>Находят в новости то, что есть в профиле (продукты, поставщики, конкуренты, регионы, риски), определяют
            канал влияния — рост затрат, сбой поставок, спрос, ставка, господдержка — и считают релевантность, влияние,
            срочность и уверенность. Работают офлайн, без ключей.</p>
        </Layer>

        <Layer icon={Bot} title="2. LLM — по кнопке, для текста разбора"
          state={!status ? "…" : status.llm.state === "gateway" ? `${status.llm.label} (${status.llm.model})` : status.llm.label}
          tone={status?.llm.state === "gateway" ? "bg-emerald-50 text-emerald-700"
            : status?.llm.state === "budget" || status?.llm.state === "mock" ? "bg-amber-50 text-amber-800" : "bg-ink-100 text-ink-500"}>
          <p>Языковая модель (только разрешённые кейсом: Qwen3.6, GLM-5.3, Gemma 4 и др. — через шлюз организаторов) переписывает разбор понятным языком по структурированной схеме, а факты
            сверяются с текстом источника. Баллы и ранжирование она не меняет. Вызывается вручную на странице события,
            без языковой модели сервис полностью работает на правилах.</p>
        </Layer>
      </div>
    </Modal>
  );
}
