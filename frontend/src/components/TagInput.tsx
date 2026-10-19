import { ChevronDown, Plus, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { FieldOptions } from "../types";

interface Props {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  hint?: string;
  // варианты для выпадающего списка; без них — обычное поле со списком значений
  options?: FieldOptions;
  suggestedTitle?: string;
}

type Item = { kind: "custom" | "option"; value: string; group?: string };

const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ").trim();

// поле со списком значений: выбор из вариантов или своё значение.
// Enter добавляет элемент, через ";" можно вставить несколько сразу
// (запятую не используем — она часто встречается внутри самих формулировок)
export default function TagInput({ label, value, onChange, placeholder, hint, options, suggestedTitle }: Props) {
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const known = useMemo(
    () => new Set([...(options?.suggested || []), ...(options?.other || [])].map(norm)),
    [options],
  );

  const items: Item[] = useMemo(() => {
    if (!options) return [];
    const chosen = new Set(value.map(norm));
    const q = norm(draft);
    const fits = (v: string) => !chosen.has(norm(v)) && (!q || norm(v).includes(q));
    const out: Item[] = [];
    if (q && !chosen.has(q) && !known.has(q)) out.push({ kind: "custom", value: draft.trim() });
    options.suggested.filter(fits).forEach((v) => out.push({ kind: "option", value: v, group: "suggested" }));
    options.other.filter(fits).slice(0, q ? 60 : 40).forEach((v) => out.push({ kind: "option", value: v, group: "other" }));
    return out;
  }, [options, value, draft, known]);

  useEffect(() => setActive(0), [draft, open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const addMany = (raw: string) => {
    const parts = raw.split(";").map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    parts.forEach((p) => {
      if (!next.some((x) => norm(x) === norm(p))) next.push(p);
    });
    onChange(next);
    setDraft("");
  };

  const choose = (it: Item) => {
    addMany(it.value);
    inputRef.current?.focus();
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (open && items[active]) choose(items[active]);
      else addMany(draft);
    } else if (e.key === "ArrowDown" && options) {
      e.preventDefault();
      if (!open) setOpen(true);
      else setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === "ArrowUp" && options) {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Escape" && open) {
      e.stopPropagation();
      setOpen(false);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  const groupTitle = (g?: string) => (g === "suggested" ? suggestedTitle || "Типично для отрасли" : "Другие варианты");

  return (
    <div ref={boxRef} className="relative">
      <label className="label">{label}</label>
      <div
        className="flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-2 py-1.5 focus-within:border-ink-500 focus-within:ring-2 focus-within:ring-ink-200"
        onClick={() => inputRef.current?.focus()}
      >
        {value.map((v) => {
          const custom = options && !known.has(norm(v));
          return (
            <span key={v} title={custom ? "Своё значение" : undefined}
              className={`inline-flex items-center gap-1 rounded-md py-0.5 pl-2 pr-1 text-sm text-ink-700 ${
                custom ? "border border-dashed border-ink-300 bg-white" : "bg-ink-100"}`}>
              {v}
              <button type="button" className="rounded p-0.5 text-ink-400 hover:bg-ink-200 hover:text-ink-700"
                onClick={(e) => { e.stopPropagation(); onChange(value.filter((x) => x !== v)); }} aria-label={`Удалить ${v}`}>
                <X size={12} />
              </button>
            </span>
          );
        })}
        <input
          ref={inputRef}
          className="min-w-[140px] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-ink-400"
          value={draft}
          placeholder={value.length ? (options ? "Выбрать или добавить своё…" : "") : placeholder
            || (options ? "Выберите из списка или введите своё" : "Введите и нажмите Enter")}
          onChange={(e) => { setDraft(e.target.value); if (options) setOpen(true); }}
          onFocus={() => options && setOpen(true)}
          onKeyDown={onKey}
          // без вариантов ведём себя как раньше: ушли из поля — значение добавилось
          onBlur={() => !options && addMany(draft)}
          role={options ? "combobox" : undefined}
          aria-expanded={options ? open : undefined}
          aria-controls={options ? listId : undefined}
          aria-label={label}
        />
        {options && (
          <button type="button" tabIndex={-1} className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
            onMouseDown={(e) => { e.preventDefault(); setOpen((o) => !o); inputRef.current?.focus(); }}
            aria-label="Показать варианты">
            <ChevronDown size={15} />
          </button>
        )}
      </div>
      {options && open && (
        <ul id={listId} role="listbox"
          className="absolute left-0 right-0 z-30 mt-1 max-h-64 overflow-y-auto rounded-lg border border-ink-200 bg-white py-1 shadow-lg">
          {items.length === 0 && (
            <li className="px-3 py-2 text-sm text-ink-400">
              {draft ? "Уже добавлено" : "Все варианты выбраны — введите своё значение"}
            </li>
          )}
          {items.map((it, i) => {
            const header = it.kind === "option" && (i === 0 || items[i - 1].group !== it.group || items[i - 1].kind === "custom");
            return (
              <li key={it.kind + it.value} role="presentation">
                {header && (
                  <div className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-400">
                    {groupTitle(it.group)}
                  </div>
                )}
                <button type="button" role="option" aria-selected={i === active}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${
                    i === active ? "bg-ink-100 text-ink-900" : "text-ink-700 hover:bg-ink-50"}`}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(it)}>
                  {it.kind === "custom" ? (
                    <><Plus size={14} className="shrink-0 text-ink-400" /> Добавить своё: «{it.value}»</>
                  ) : it.value}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {hint && <p className="mt-1 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}
