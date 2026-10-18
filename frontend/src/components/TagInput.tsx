import { X } from "lucide-react";
import { useState } from "react";
import type { KeyboardEvent } from "react";

interface Props {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  hint?: string;
}

// поле со списком значений: Enter добавляет элемент, через ";" можно вставить несколько сразу
// (запятую не используем — она часто встречается внутри самих формулировок)
export default function TagInput({ label, value, onChange, placeholder, hint }: Props) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const parts = draft.split(";").map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    parts.forEach((p) => {
      if (!next.includes(p)) next.push(p);
    });
    onChange(next);
    setDraft("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-2 py-1.5 focus-within:border-ink-500 focus-within:ring-2 focus-within:ring-ink-200">
        {value.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-md bg-ink-100 py-0.5 pl-2 pr-1 text-sm text-ink-700">
            {v}
            <button type="button" className="rounded p-0.5 text-ink-400 hover:bg-ink-200 hover:text-ink-700"
              onClick={() => onChange(value.filter((x) => x !== v))} aria-label={`Удалить ${v}`}>
              <X size={12} />
            </button>
          </span>
        ))}
        <input
          className="min-w-[140px] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-ink-400"
          value={draft}
          placeholder={value.length ? "" : placeholder || "Введите и нажмите Enter"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          onBlur={add}
        />
      </div>
      {hint && <p className="mt-1 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}
