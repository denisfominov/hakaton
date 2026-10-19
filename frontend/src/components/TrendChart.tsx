import { ArrowRight, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TrendKind, TrendPoint } from "../types";
import { formatDate, plural } from "../utils";

const KINDS: { key: TrendKind; label: string; color: string; text: string }[] = [
  { key: "risk", label: "Риски", color: "#e11d48", text: "text-rose-700" },
  { key: "opportunity", label: "Возможности", color: "#059669", text: "text-emerald-700" },
  { key: "neutral", label: "Нейтральные", color: "#cbd5e1", text: "text-ink-500" },
];

type Row = TrendPoint & { label: string };

// подсказка по наведению: какие новости в столбце (переход — по клику на столбец)
function HoverTip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const total = row.risk + row.opportunity + row.neutral;
  if (!total) return null;
  return (
    <div className="max-w-[320px] rounded-lg border border-ink-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink-900">{row.label}</div>
      {KINDS.map((k) => row.events[k.key].length > 0 && (
        <div key={k.key} className="mt-1.5">
          <div className={`font-medium ${k.text}`}>{k.label}: {row[k.key]}</div>
          <ul className="mt-0.5 space-y-0.5 text-ink-700">
            {row.events[k.key].slice(0, 3).map((e) => <li key={e.id} className="line-clamp-1">• {e.title}</li>)}
            {row.events[k.key].length > 3 && <li className="text-ink-400">и ещё {row.events[k.key].length - 3}</li>}
          </ul>
        </div>
      ))}
      <div className="mt-2 border-t border-ink-100 pt-1.5 text-ink-400">Нажмите на столбец, чтобы открыть новости</div>
    </div>
  );
}

export default function TrendChart({ trend, step }: { trend: TrendPoint[]; step: "day" | "week" }) {
  const [picked, setPicked] = useState<{ day: string; kind: TrendKind } | null>(null);
  const rows: Row[] = trend.map((d) => ({ ...d, label: (step === "week" ? "с " : "") + formatDate(d.day, false) }));
  const sel = picked ? rows.find((r) => r.day === picked.day) : null;

  return (
    <>
      <div className="mt-4 h-60">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} barCategoryGap="25%">
            <CartesianGrid vertical={false} stroke="#eef1f4" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} stroke="#94a3b8" />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} stroke="#94a3b8" width={28} />
            <Tooltip cursor={{ fill: "#f1f5f9" }} content={<HoverTip />} />
            <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
            {KINDS.map((k, i) => (
              <Bar key={k.key} dataKey={k.key} name={k.label} stackId="a" fill={k.color} cursor="pointer"
                radius={i === KINDS.length - 1 ? [3, 3, 0, 0] : undefined}
                onClick={(d: { payload?: Row }) => d.payload && setPicked({ day: d.payload.day, kind: k.key })} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {sel && picked && (
        <div className="mt-3 rounded-lg border border-ink-200 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm font-medium">
              {step === "week" ? "Неделя " : ""}{sel.label}: {sel.risk + sel.opportunity + sel.neutral}{" "}
              {plural(sel.risk + sel.opportunity + sel.neutral, "событие", "события", "событий")}
            </div>
            <button className="btn-ghost !p-1" onClick={() => setPicked(null)} aria-label="Закрыть список"><X size={15} /></button>
          </div>
          {/* выбранный тип — первым, остальные ниже */}
          {[...KINDS].sort((a, b) => (a.key === picked.kind ? -1 : b.key === picked.kind ? 1 : 0)).map((k) =>
            sel.events[k.key].length > 0 && (
              <div key={k.key} className="mt-2">
                <div className={`text-xs font-medium uppercase tracking-wide ${k.text}`}>{k.label}</div>
                <ul className="mt-1 divide-y divide-ink-100">
                  {sel.events[k.key].map((e) => (
                    <li key={e.id}>
                      <Link to={`/events/${e.id}`} className="group flex items-center gap-3 py-1.5 text-sm hover:text-ink-900">
                        <span className="w-8 shrink-0 text-right font-semibold tabular-nums text-ink-500">{e.priority}</span>
                        <span className="min-w-0 flex-1 text-ink-700 group-hover:underline">{e.title}</span>
                        <ArrowRight size={14} className="shrink-0 text-ink-300 group-hover:text-ink-700" />
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
      )}
    </>
  );
}
