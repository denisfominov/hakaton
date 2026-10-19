import { Check, Globe, Hash, LineChart, Plus, RotateCcw, Search, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import Modal from "../components/Modal";
import { useApp } from "../context";
import type { Profile } from "../types";

const EMPTY_FORM = { url: "", inn: "", name: "", industry: "", description: "" };

function AddCompany({ onDone }: { onDone: () => void }) {
  const { reloadProfiles, setProfileId, bumpData, toast } = useApp();
  const navigate = useNavigate();
  const [f, setF] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [industries, setIndustries] = useState<string[]>([]);

  useEffect(() => {
    api.profileOptions("").then((o) => setIndustries(o.industries)).catch(() => undefined);
  }, []);

  const ready = f.url.trim() || f.inn.trim() || f.name.trim().length >= 2;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setErrors([]);
    try {
      const res = await api.lookupCompany(f);
      const p = await api.createProfile({ ...res.suggestion.profile, autofilled: true });
      await reloadProfiles();
      setProfileId(p.id);
      bumpData();
      const sources = res.suggestion.profile.autofill_info?.sources || [];
      toast(`Компания добавлена${sources.length ? `: данные из ${sources.join(" и ")}` : ""}. Проверьте профиль`);
      if (res.errors.length) toast(res.errors.join("; "), "error");
      onDone();
      navigate("/profile");
    } catch (err: any) {
      setErrors([err.message]);
    } finally {
      setBusy(false);
    }
  };

  const set = (k: keyof typeof EMPTY_FORM, v: string) => setF((x) => ({ ...x, [k]: v }));

  return (
    <form onSubmit={submit} className="space-y-4">
      <datalist id="company-industries">{industries.map((i) => <option key={i} value={i} />)}</datalist>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="c-url">Сайт компании</label>
          <div className="relative">
            <Globe size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input id="c-url" className="input !pl-9" value={f.url} placeholder="company.ru" autoFocus
              onChange={(e) => set("url", e.target.value)} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="c-inn">ИНН</label>
          <div className="relative">
            <Hash size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input id="c-inn" className="input !pl-9" value={f.inn} inputMode="numeric" placeholder="10 или 12 цифр"
              onChange={(e) => set("inn", e.target.value.replace(/[^\d]/g, "").slice(0, 12))} />
          </div>
        </div>
      </div>
      <p className="text-xs text-ink-500">
        Достаточно ИНН или сайта. Сервис параллельно ищет компанию в открытых источниках: ЕГРЮЛ (название, регион,
        ОГРН), порталы проверки контрагентов Checko и «За честный бизнес» (виды деятельности, выручка, численность,
        официальный сайт), сайт компании (что продаёт и кому) и Википедия. Найденное разложится по разделам профиля —
        всё можно отредактировать.
      </p>
      {busy && (
        <div className="rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-700">
          Ищем: ЕГРЮЛ → Checko, «За честный бизнес», сайт компании, Википедия… обычно 3–10 секунд.
        </div>
      )}
      <details className="rounded-lg border border-ink-200 px-3 py-2">
        <summary className="cursor-pointer text-sm text-ink-700">Уточнить вручную (необязательно)</summary>
        <div className="mt-3 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="c-name">Название</label>
              <input id="c-name" className="input" value={f.name} placeholder="Если не указано — из ЕГРЮЛ или сайта"
                onChange={(e) => set("name", e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="c-ind">Отрасль</label>
              <input id="c-ind" className="input" value={f.industry} list="company-industries"
                placeholder="Определится автоматически" onChange={(e) => set("industry", e.target.value)} />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="c-desc">Пара фраз о компании</label>
            <textarea id="c-desc" className="input min-h-[70px]" value={f.description}
              placeholder="Что продаёт и кому, откуда закупает. Например: поставляем станки из Китая заводам Урала"
              onChange={(e) => set("description", e.target.value)} />
          </div>
        </div>
      </details>
      {errors.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{errors.join("; ")}</div>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onDone}>Отмена</button>
        <button type="submit" className="btn-primary" disabled={!ready || busy}>
          <Wand2 size={15} /> {busy ? "Ищем данные и заполняем…" : "Найти и заполнить профиль"}
        </button>
      </div>
    </form>
  );
}

function filled(p: Profile) {
  const keys = ["products", "clients", "suppliers", "competitors", "regions", "goals", "risks", "keywords"] as const;
  return keys.filter((k) => p[k]?.length).length;
}

export default function CompaniesPage() {
  const { profiles, profileId, setProfileId, reloadProfiles, reloadStatus, status, bumpData, toast } = useApp();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [adding, setAdding] = useState(params.get("add") === "1");
  const [q, setQ] = useState("");
  const [removing, setRemoving] = useState<Profile | null>(null);

  const open = (id: string, to: string) => {
    setProfileId(id);
    bumpData();
    navigate(to);
  };

  const remove = async () => {
    if (!removing) return;
    try {
      await api.deleteProfile(removing.id);
      setRemoving(null);
      await reloadProfiles();
      await reloadStatus();
      bumpData();
      toast(`Компания «${removing.name}» удалена`);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const restore = async () => {
    try {
      const r = await api.restorePresets();
      await reloadProfiles();
      await reloadStatus();
      bumpData();
      toast(r.restored.length ? `Восстановлено: ${r.restored.join(", ")}` : "Нечего восстанавливать");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const closeAdd = () => {
    setAdding(false);
    if (params.get("add")) setParams({});
  };

  const list = profiles.filter((p) => !q || `${p.name} ${p.industry}`.toLowerCase().includes(q.toLowerCase()));
  const deleted = status?.deleted_presets || [];

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Выбор компании</h1>
          <p className="mt-1 text-sm text-ink-500">Для какой компании анализировать новости. Можно добавить свою по сайту или ИНН</p>
        </div>
        <button className="btn-primary self-start whitespace-nowrap" onClick={() => setAdding(true)}><Plus size={15} /> Добавить компанию</button>
      </div>

      {deleted.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-ink-200 bg-white px-4 py-3 text-sm">
          <span className="text-ink-700">Удалены встроенные компании: {deleted.map((d) => d.name).join(", ")}</span>
          <button className="btn-ghost !py-1" onClick={restore}><RotateCcw size={14} /> Восстановить</button>
        </div>
      )}

      {profiles.length > 6 && (
        <div className="relative max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className="input !pl-9" placeholder="Найти компанию" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {list.map((p) => {
          const current = p.id === profileId;
          return (
            <div key={p.id} className={`card flex flex-col p-4 ${current ? "ring-2 ring-ink-900" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold leading-snug">{p.name}</div>
                  <div className="mt-0.5 text-sm text-ink-500">{p.industry || "Отрасль не указана"}</div>
                </div>
                {current && (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-ink-900 px-2 py-0.5 text-xs font-medium text-white">
                    <Check size={12} /> Анализируем
                  </span>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                <span className="rounded-md bg-ink-100 px-2 py-0.5 text-ink-700">{p.is_demo ? "Встроенная" : "Добавлена вами"}</span>
                {p.ticker && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-sky-50 px-2 py-0.5 text-sky-800" title="Публичная компания: новости размечаются по реакции акций">
                    <LineChart size={11} /> {p.ticker}
                  </span>
                )}
                {p.inn && <span className="rounded-md bg-ink-100 px-2 py-0.5 text-ink-700">ИНН {p.inn}</span>}
                {p.autofilled && <span className="rounded-md bg-amber-50 px-2 py-0.5 text-amber-800">Профиль не подтверждён</span>}
                <span className="rounded-md bg-ink-100 px-2 py-0.5 text-ink-500">Заполнено разделов: {filled(p)} из 8</span>
              </div>
              <div className="mt-auto flex flex-wrap gap-2 pt-4">
                <button className="btn-primary !py-1.5 text-sm" onClick={() => open(p.id, "/")}>Анализировать</button>
                <button className="btn-secondary !py-1.5 text-sm" onClick={() => open(p.id, "/profile")}>Профиль</button>
                <button className="btn-ghost ml-auto !px-2 !py-1.5 text-sm !text-red-700" onClick={() => setRemoving(p)}
                  disabled={profiles.length <= 1} aria-label={`Удалить ${p.name}`} title="Удалить компанию">
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {adding && (
        <Modal title="Добавить компанию" onClose={closeAdd} wide>
          <AddCompany onDone={closeAdd} />
        </Modal>
      )}

      {removing && (
        <Modal title="Удалить компанию?" onClose={() => setRemoving(null)}>
          <p className="text-sm text-ink-700">
            «{removing.name}», её избранное, оценки и кэш анализа будут удалены. Действия в плане останутся.
            {removing.is_demo && " Это встроенная компания — её можно будет восстановить."}
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-secondary" onClick={() => setRemoving(null)}>Отмена</button>
            <button className="btn-primary !bg-red-600 hover:!bg-red-700" onClick={remove}>Удалить</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
