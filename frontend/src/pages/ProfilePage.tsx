import { Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import Modal from "../components/Modal";
import { ErrorBox, Loading } from "../components/States";
import TagInput from "../components/TagInput";
import { useApp } from "../context";
import type { Profile } from "../types";

type ProfileData = Omit<Profile, "id" | "is_demo" | "updated_at">;

const EMPTY: ProfileData = {
  name: "", description: "", industry: "", subindustries: [], regions: [], products: [], clients: [],
  suppliers: [], competitors: [], goals: [], priorities: [], risks: [], investment_plans: [], keywords: [],
};

const LIST_FIELDS: { key: keyof ProfileData; label: string; hint?: string; placeholder?: string }[] = [
  { key: "subindustries", label: "Подотрасли", placeholder: "Например: трубная продукция" },
  { key: "regions", label: "Регионы присутствия", hint: "Регионы РФ и страны: продажи, производство, закупки" },
  { key: "products", label: "Продукты и услуги" },
  { key: "clients", label: "Ключевые клиенты", placeholder: "Компании или сегменты" },
  { key: "suppliers", label: "Ключевые поставщики и закупки",
    hint: "В скобках можно указать страну или регион: «Субстанции (Индия)» — так система поймёт географию риска" },
  { key: "competitors", label: "Конкуренты" },
  { key: "goals", label: "Бизнес-цели" },
  { key: "priorities", label: "Стратегические приоритеты" },
  { key: "risks", label: "Основные риски и ограничения", hint: "Например: «Долговая нагрузка с плавающей ставкой» — повысит вес новостей о ставке" },
  { key: "investment_plans", label: "Инвестиционные планы" },
  { key: "keywords", label: "Интересующие темы и ключевые слова" },
];

function toData(p: Profile): ProfileData {
  const { id: _id, is_demo: _d, updated_at: _u, ...rest } = p;
  return { ...EMPTY, ...rest };
}

export default function ProfilePage() {
  const { profile, profiles, setProfileId, reloadProfiles, bumpData, toast } = useApp();
  const [form, setForm] = useState<ProfileData>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (profile) {
      setForm(toData(profile));
      setDirty(false);
      setError(null);
    }
  }, [profile?.id, profile?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!profiles.length) return <Loading />;
  if (!profile) return <ErrorBox error="Профиль не выбран" />;

  const set = <K extends keyof ProfileData>(k: K, v: ProfileData[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    setDirty(true);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (form.name.trim().length < 2) {
      setError("Укажите название компании");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateProfile(profile.id, form);
      await reloadProfiles();
      bumpData();
      setDirty(false);
      toast("Профиль сохранён — оценки событий пересчитаны");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    try {
      await api.resetProfile(profile.id);
      await reloadProfiles();
      bumpData();
      toast("Демо-профиль восстановлен");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (newName.trim().length < 2) return;
    try {
      const p = await api.createProfile({ ...EMPTY, name: newName.trim() });
      await reloadProfiles();
      setProfileId(p.id);
      bumpData();
      setCreating(false);
      setNewName("");
      toast("Профиль создан — заполните отрасль, регионы и контрагентов");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  const remove = async () => {
    try {
      await api.deleteProfile(profile.id);
      setConfirmDelete(false);
      await reloadProfiles();
      bumpData();
      toast("Профиль удалён");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  return (
    <>
    <form onSubmit={save} className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Профиль компании</h1>
          <p className="mt-1 text-sm text-ink-500">Контекст, по которому система решает, что важно именно для этой компании</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-secondary" onClick={() => setCreating(true)}><Plus size={15} /> Новый профиль</button>
          {profile.is_demo ? (
            <button type="button" className="btn-secondary" onClick={reset} title="Вернуть исходные значения демо-профиля">
              <RotateCcw size={15} /> Сбросить демо
            </button>
          ) : (
            <button type="button" className="btn-secondary !text-red-700" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={15} /> Удалить
            </button>
          )}
          <button type="submit" className="btn-primary" disabled={!dirty || saving}>
            <Save size={15} /> {saving ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </div>

      {profile.is_demo && (
        <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
          Это синтетический демо-профиль, он не описывает реальную компанию. Его можно менять: например, уберите конкурента
          или поставщика и посмотрите, как изменятся оценки в ленте.
        </div>
      )}
      {error && <ErrorBox error={error} />}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <section className="card space-y-4 p-5">
            <h2 className="section-title">Основное</h2>
            <div>
              <label className="label" htmlFor="p-name">Название</label>
              <input id="p-name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="p-industry">Отрасль</label>
              <input id="p-industry" className="input" value={form.industry} placeholder="Например: Металлургия"
                onChange={(e) => set("industry", e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="p-desc">Краткое описание бизнеса</label>
              <textarea id="p-desc" className="input min-h-[80px]" value={form.description}
                placeholder="Масштаб, структура выручки, экспорт/импорт…"
                onChange={(e) => set("description", e.target.value)} />
            </div>
          </section>

          <section className="card space-y-4 p-5">
            <h2 className="section-title">Бизнес-контекст</h2>
            {LIST_FIELDS.map((f) => (
              <TagInput key={f.key} label={f.label} hint={f.hint} placeholder={f.placeholder}
                value={form[f.key] as string[]} onChange={(v) => set(f.key, v as never)} />
            ))}
          </section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <div className="card p-5 text-sm">
            <h2 className="section-title">Как профиль влияет на анализ</h2>
            <ul className="mt-3 space-y-2.5 text-ink-700">
              <li><b>Отрасль и продукты</b> — базовая релевантность и каналы «спрос», «цены», «пошлины».</li>
              <li><b>Регионы</b> — события в этих регионах получают дополнительный вес.</li>
              <li><b>Поставщики</b> — новости о росте цен и сбоях становятся рисками затрат и поставок.</li>
              <li><b>Конкуренты</b> — их аварии дают возможность, а расширение — риск.</li>
              <li><b>Цели, приоритеты, инвестпланы</b> — помогают найти возможности (льготное финансирование, технологии).</li>
              <li><b>Риски</b> — например, долг с плавающей ставкой делает важными новости о ключевой ставке.</li>
            </ul>
          </div>
          <div className="card p-5 text-xs text-ink-500">
            Данные профиля хранятся локально в SQLite. Не вносите конфиденциальные сведения реальных компаний без разрешения.
          </div>
        </aside>
      </div>

      {dirty && (
        <div className="sticky bottom-4 z-10 flex items-center justify-between gap-3 rounded-xl border border-ink-200 bg-white px-4 py-3 shadow-lg">
          <span className="text-sm text-ink-700">Есть несохранённые изменения</span>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={() => { setForm(toData(profile)); setDirty(false); }}>Отменить</button>
            <button type="submit" className="btn-primary" disabled={saving}>Сохранить</button>
          </div>
        </div>
      )}
    </form>

      {creating && (
        <Modal title="Новый профиль компании" onClose={() => setCreating(false)}>
          <form onSubmit={create} className="space-y-4">
            <div>
              <label className="label" htmlFor="new-name">Название компании</label>
              <input id="new-name" className="input" value={newName} autoFocus onChange={(e) => setNewName(e.target.value)} />
            </div>
            <p className="text-xs text-ink-500">После создания заполните отрасль, регионы, поставщиков и конкурентов — без них оценки будут низкими.</p>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setCreating(false)}>Отмена</button>
              <button type="submit" className="btn-primary" disabled={newName.trim().length < 2}>Создать</button>
            </div>
          </form>
        </Modal>
      )}

      {confirmDelete && (
        <Modal title="Удалить профиль?" onClose={() => setConfirmDelete(false)}>
          <p className="text-sm text-ink-700">Профиль «{profile.name}», его избранное и кэш анализа будут удалены. Действия в плане останутся.</p>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setConfirmDelete(false)}>Отмена</button>
            <button type="button" className="btn-primary !bg-red-600 hover:!bg-red-700" onClick={remove}>Удалить</button>
          </div>
        </Modal>
      )}
    </>
  );
}
