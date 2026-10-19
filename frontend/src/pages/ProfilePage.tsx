import { Plus, RotateCcw, Save, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import Modal from "../components/Modal";
import { ErrorBox, Loading } from "../components/States";
import TagInput from "../components/TagInput";
import { useApp } from "../context";
import type { Profile, ProfileListField, ProfileOptions } from "../types";

type ProfileData = Omit<Profile, "id" | "is_demo" | "updated_at">;

const EMPTY: ProfileData = {
  name: "", aliases: [], kind: "", source_note: "", description: "", industry: "", subindustries: [], regions: [],
  products: [], clients: [], suppliers: [], competitors: [], goals: [], priorities: [], risks: [],
  investment_plans: [], keywords: [], autofilled: false, autofill_info: {},
};

type FieldDef = { key: ProfileListField; label: string; hint?: string; placeholder?: string };

const SECTIONS: { title: string; hint: string; fields: FieldDef[] }[] = [
  {
    title: "Что продаёт и кому",
    hint: "Рынок компании: что продаёт, где работает, кто покупает, у кого закупает и с кем конкурирует",
    fields: [
      { key: "subindustries", label: "Подотрасли" },
      { key: "products", label: "Продукты и услуги" },
      { key: "clients", label: "Ключевые клиенты", hint: "Компании или сегменты" },
      { key: "regions", label: "Регионы присутствия", hint: "Регионы РФ и страны: продажи, производство, закупки" },
      { key: "suppliers", label: "Ключевые поставщики и закупки",
        hint: "В скобках можно указать страну: «Производители станков (Китай)» — так система поймёт географию риска" },
      { key: "competitors", label: "Конкуренты" },
    ],
  },
  {
    title: "Цели и риски",
    hint: "По ним система находит возможности и решает, какие риски касаются компании сильнее",
    fields: [
      { key: "goals", label: "Бизнес-цели" },
      { key: "priorities", label: "Стратегические приоритеты" },
      { key: "risks", label: "Основные риски и ограничения",
        hint: "Например: «Кредитная нагрузка на оборотный капитал» — повысит вес новостей о ставке" },
      { key: "investment_plans", label: "Инвестиционные планы" },
    ],
  },
];

function toData(p: Profile): ProfileData {
  const { id: _id, is_demo: _d, updated_at: _u, ...rest } = p;
  return { ...EMPTY, ...rest };
}

function countFilled(d: ProfileData) {
  return SECTIONS.flatMap((s) => s.fields).filter((f) => d[f.key].length).length + (d.keywords.length ? 1 : 0);
}

export default function ProfilePage() {
  const { profile, profiles, setProfileId, reloadProfiles, bumpData, toast } = useApp();
  const [form, setForm] = useState<ProfileData>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newCo, setNewCo] = useState({ name: "", industry: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [options, setOptions] = useState<ProfileOptions | null>(null);

  useEffect(() => {
    if (profile) {
      setForm(toData(profile));
      setDirty(false);
      setError(null);
    }
  }, [profile?.id, profile?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  // варианты в списках зависят от отрасли: перезапрашиваем, когда её поменяли (с задержкой — пока печатают)
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      api.profileOptions(form.industry).then((o) => !cancelled && setOptions(o)).catch(() => undefined);
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [form.industry, profile?.updated_at]);

  if (!profiles.length) return <Loading />;
  if (!profile) return <ErrorBox error="Профиль не выбран" />;

  const set = <K extends keyof ProfileData>(k: K, v: ProfileData[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    setDirty(true);
  };

  const suggestedTitle = options?.template ? `Типично для отрасли «${options.template}»` : undefined;
  const opts = (k: ProfileListField) => options?.fields[k];

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (form.name.trim().length < 2) {
      setError("Укажите название компании");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateProfile(profile.id, { ...form, autofilled: false, autofill_info: {} });
      await reloadProfiles();
      bumpData();
      setDirty(false);
      toast(profile.autofilled ? "Профиль подтверждён — анализ идёт по вашей версии" : "Профиль сохранён — оценки событий пересчитаны");
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
      toast("Исходный профиль восстановлен");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  // дополнить пустые поля вариантами по отрасли и описанию; заполненные поля не трогаем
  const fillEmpty = async () => {
    try {
      const s = await api.suggestProfile({ name: form.name, industry: form.industry, description: form.description });
      let added = 0;
      const next = { ...form };
      const keys: ProfileListField[] = [...SECTIONS.flatMap((x) => x.fields.map((f) => f.key)), "keywords"];
      keys.forEach((k) => {
        if (!next[k].length && s.profile[k]?.length) {
          next[k] = s.profile[k];
          added += s.profile[k].length;
        }
      });
      if (!next.aliases.length && s.profile.aliases.length) {
        next.aliases = s.profile.aliases;
        added += s.profile.aliases.length;
      }
      if (!next.industry && s.profile.industry) next.industry = s.profile.industry;
      if (!added) {
        toast(s.template ? "Пустых полей нет — менять заполненное не стали" : "Не удалось определить отрасль: выберите её из списка");
        return;
      }
      setForm(next);
      setDirty(true);
      toast(`Добавлено вариантов: ${added}. Проверьте и сохраните`);
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (newCo.name.trim().length < 2) return;
    setBusy(true);
    try {
      const s = await api.suggestProfile(newCo);
      const p = await api.createProfile({
        ...s.profile, autofilled: true, autofill_info: { template: s.template, from_description: s.from_description },
      });
      await reloadProfiles();
      setProfileId(p.id);
      bumpData();
      setCreating(false);
      setNewCo({ name: "", industry: "", description: "" });
      toast(s.template ? "Профиль заполнен по отрасли — проверьте и сохраните" : "Профиль создан — заполните поля из списков");
    } catch (err: any) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
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

  const info = profile.autofill_info || {};
  const fromDesc = Object.values(info.from_description || {}).flat();

  return (
    <>
    <datalist id="industry-options">
      {options?.industries.map((i) => <option key={i} value={i} />)}
    </datalist>
    <form onSubmit={save} className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Профиль компании</h1>
          <p className="mt-1 text-sm text-ink-500">Контекст, по которому система решает, что важно именно для этой компании</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-secondary" onClick={() => setCreating(true)}><Plus size={15} /> Новая компания</button>
          <button type="button" className="btn-secondary" onClick={fillEmpty} title="Заполнить пустые поля вариантами по отрасли и описанию">
            <Wand2 size={15} /> Дополнить по отрасли
          </button>
          {profile.is_demo ? (
            <button type="button" className="btn-secondary" onClick={reset} title="Вернуть исходные значения встроенного профиля">
              <RotateCcw size={15} /> Сбросить
            </button>
          ) : (
            <button type="button" className="btn-secondary !text-red-700" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={15} /> Удалить
            </button>
          )}
          <button type="submit" className="btn-primary" disabled={(!dirty && !profile.autofilled) || saving}>
            <Save size={15} /> {saving ? "Сохраняем…" : profile.autofilled && !dirty ? "Подтвердить" : "Сохранить"}
          </button>
        </div>
      </div>

      {profile.autofilled && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <b>Профиль заполнен автоматически</b>
          {info.template ? <> по типичному профилю отрасли «{info.template}»</> : null}
          {fromDesc.length ? <> и описанию компании (нашлось: {fromDesc.slice(0, 6).join(", ")}{fromDesc.length > 6 ? "…" : ""})</> : null}.
          {" "}Это предложение сервиса: уберите лишнее, добавьте своё из списков или вручную и нажмите «Подтвердить».
          Дальше оценки новостей считаются по вашей версии профиля.
        </div>
      )}
      {profile.is_demo && profile.kind === "real" && (
        <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
          {profile.source_note || "Профиль реальной компании, составлен командой по открытым источникам."} Профиль можно
          менять — например, убрать конкурента или поставщика и посмотреть, как изменятся оценки. «Сбросить» вернёт исходный вариант.
        </div>
      )}
      {profile.is_demo && profile.kind !== "real" && (
        <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
          Это синтетический профиль, он не описывает реальную компанию. Его можно менять: например, уберите конкурента
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
              <input id="p-industry" className="input" value={form.industry} list="industry-options"
                placeholder="Выберите из списка или впишите свою" onChange={(e) => set("industry", e.target.value)} />
              <p className="mt-1 text-xs text-ink-400">От отрасли зависят варианты в списках ниже: типичные для неё показываются первыми</p>
            </div>
            <div>
              <label className="label" htmlFor="p-desc">Краткое описание бизнеса</label>
              <textarea id="p-desc" className="input min-h-[80px]" value={form.description}
                placeholder="Масштаб, структура выручки, экспорт/импорт…"
                onChange={(e) => set("description", e.target.value)} />
            </div>
          </section>

          {SECTIONS.map((sec) => (
            <section key={sec.title} className="card space-y-4 p-5">
              <div>
                <h2 className="section-title">{sec.title}</h2>
                <p className="mt-0.5 text-xs text-ink-500">{sec.hint}</p>
              </div>
              {sec.fields.map((f) => (
                <TagInput key={f.key} label={f.label} hint={f.hint} placeholder={f.placeholder}
                  options={opts(f.key)} suggestedTitle={suggestedTitle}
                  value={form[f.key]} onChange={(v) => set(f.key, v)} />
              ))}
            </section>
          ))}

          <section className="card space-y-4 p-5">
            <div>
              <h2 className="section-title">Как искать новости</h2>
              <p className="mt-0.5 text-xs text-ink-500">Имена и темы, по которым новость связывается с компанией напрямую</p>
            </div>
            <TagInput label="Другие названия и бренды" value={form.aliases} onChange={(v) => set("aliases", v)}
              placeholder="Например: Сбер, Сбербанк"
              hint="Как компанию называют в новостях. Избегайте обычных слов («Победа», «Самолёт»): они дадут ложные совпадения" />
            <TagInput label="Интересующие темы и ключевые слова" options={opts("keywords")} suggestedTitle={suggestedTitle}
              value={form.keywords} onChange={(v) => set("keywords", v)} />
          </section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <div className="card p-5 text-sm">
            <h2 className="section-title">Как заполнять</h2>
            <ul className="mt-3 space-y-2.5 text-ink-700">
              <li>В каждом поле — выпадающий список: сначала варианты, типичные для отрасли, затем остальные.</li>
              <li>Нет подходящего — введите своё и нажмите Enter. Свои значения отмечены пунктиром и появятся в списках других профилей.</li>
              <li>Формулируйте так, как пишут в новостях: «Рост тарифов РЖД», а не «логистика ↑».</li>
            </ul>
            <p className="mt-3 text-xs text-ink-500">Заполнено разделов: {countFilled(form)} из 12</p>
          </div>
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
        <Modal title="Новая компания" onClose={() => setCreating(false)}>
          <form onSubmit={create} className="space-y-4">
            <div>
              <label className="label" htmlFor="new-name">Название компании</label>
              <input id="new-name" className="input" value={newCo.name} autoFocus placeholder="Например: ООО «Ромашка»"
                onChange={(e) => setNewCo({ ...newCo, name: e.target.value })} />
            </div>
            <div>
              <label className="label" htmlFor="new-industry">Отрасль</label>
              <input id="new-industry" className="input" value={newCo.industry} list="industry-options"
                placeholder="Выберите из списка или впишите свою"
                onChange={(e) => setNewCo({ ...newCo, industry: e.target.value })} />
            </div>
            <div>
              <label className="label" htmlFor="new-desc">Пара фраз о компании (необязательно)</label>
              <textarea id="new-desc" className="input min-h-[80px]" value={newCo.description}
                placeholder="Что продаёт и кому, где работает, откуда закупает. Например: поставляем станки из Китая заводам Урала и Казахстана"
                onChange={(e) => setNewCo({ ...newCo, description: e.target.value })} />
            </div>
            <p className="text-xs text-ink-500">
              Сервис предложит заполнение всех разделов по отрасли и описанию. Дальше его можно отредактировать под себя —
              анализ пойдёт по вашей версии.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setCreating(false)}>Отмена</button>
              <button type="submit" className="btn-primary" disabled={newCo.name.trim().length < 2 || busy}>
                <Wand2 size={15} /> {busy ? "Заполняем…" : "Создать и заполнить"}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {confirmDelete && (
        <Modal title="Удалить профиль?" onClose={() => setConfirmDelete(false)}>
          <p className="text-sm text-ink-700">Профиль «{profile.name}», его избранное, оценки и кэш анализа будут удалены. Действия в плане останутся.</p>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setConfirmDelete(false)}>Отмена</button>
            <button type="button" className="btn-primary !bg-red-600 hover:!bg-red-700" onClick={remove}>Удалить</button>
          </div>
        </Modal>
      )}
    </>
  );
}
