import { Building2, Check, RotateCcw, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import Modal from "../components/Modal";
import { useApp } from "../context";
import type { CaseClient, Profile } from "../types";

function filled(p: Profile) {
  const keys = ["products", "clients", "suppliers", "competitors", "regions", "goals", "risks", "keywords"] as const;
  return keys.filter((k) => p[k]?.length).length;
}

// клиенты банка из данных кейса: крупный бизнес с выручкой от 15 млрд ₽ — целевая аудитория агента
function CaseClients({ onOpen }: { onOpen: (id: string) => void }) {
  const { profiles, reloadProfiles, toast } = useApp();
  const [items, setItems] = useState<CaseClient[] | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      api.clients(q.trim()).then((r) => { setItems(r.items); setSource(r.source); }).catch(() => setItems([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const added = new Map(profiles.filter((p) => p.client_id).map((p) => [p.client_id!, p.id]));

  const analyze = async (c: CaseClient) => {
    const existing = added.get(c.id);
    if (existing) return onOpen(existing);
    setBusy(c.id);
    try {
      const p = await api.clientProfile(c.id);
      await reloadProfiles();
      toast(`Профиль клиента ${c.id} собран из данных банка`);
      onOpen(p.id);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  if (items !== null && source === null) return null;
  return (
    <section className="card p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="section-title flex items-center gap-2"><Building2 size={16} /> Клиенты банка: крупный бизнес</h2>
          <p className="text-xs text-ink-500">
            Обезличенные данные кейса{source === "sample" ? " (синтетический пример — положите CSV кейса в CLIENT_DATA_DIR)" : ""}
            (df_Uid_data_hack.csv): выручка свыше 15 млрд ₽ (REVENUE_COMPANY — сумма в рублях), ОКВЭД, регион, продукты банка,
            ВЭД; контрагенты — по платежам (df_Uid_payment_hack.csv).
          </p>
        </div>
        <div className="relative w-full sm:max-w-xs">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className="input !pl-9" placeholder="ОКВЭД, город, продукт или ID" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <div className="mt-3 max-h-[420px] overflow-auto">
        <table className="w-full min-w-[800px] text-sm">
          <thead className="sticky top-0 bg-white">
            <tr className="border-b border-ink-200 text-left text-xs text-ink-500">
              <th className="py-2 pr-3 font-medium">Клиент</th>
              <th className="py-2 pr-3 font-medium">Вид деятельности</th>
              <th className="py-2 pr-3 text-right font-medium">Выручка, млрд ₽</th>
              <th className="py-2 pr-3 text-right font-medium" title="Место по выручке среди компаний того же класса ОКВЭД в наборе данных кейса">Место в отрасли</th>
              <th className="py-2 pr-3 font-medium">Продукты банка</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {(items || []).map((c) => (
              <tr key={c.id} className="align-top">
                <td className="py-2 pr-3">
                  <div className="font-medium">{c.id}</div>
                  <div className="text-xs text-ink-500">{c.city || c.region}{c.fts_countries.length ? ` · ВЭД: ${c.fts_countries.slice(0, 3).join(", ")}` : ""}</div>
                </td>
                <td className="max-w-[260px] py-2 pr-3 text-xs text-ink-700">{c.okved_code} {c.okved_name}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{c.revenue_bn}</td>
                <td className="py-2 pr-3 text-right text-xs tabular-nums text-ink-600">
                  {c.okved_class_rank ? `${c.okved_class_rank} из ${c.okved_class_companies}` : "—"}
                </td>
                <td className="max-w-[220px] py-2 pr-3 text-xs text-ink-600">{c.products.join(", ") || "—"}</td>
                <td className="py-2 text-right">
                  <button className={added.has(c.id) ? "btn-secondary !py-1 text-xs" : "btn-primary !py-1 text-xs"}
                    disabled={busy === c.id} onClick={() => analyze(c)}>
                    {busy === c.id ? "Собираем…" : added.has(c.id) ? "Открыть" : "Анализировать"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {items && !items.length && <p className="py-4 text-center text-sm text-ink-400">Ничего не найдено</p>}
      </div>
    </section>
  );
}

export default function CompaniesPage() {
  const { profiles, profileId, setProfileId, reloadProfiles, reloadStatus, status, bumpData, toast } = useApp();
  const navigate = useNavigate();
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

  const list = profiles.filter((p) => !q || `${p.name} ${p.industry}`.toLowerCase().includes(q.toLowerCase()));
  const deleted = status?.deleted_presets || [];

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Выбор компании</h1>
          <p className="mt-1 text-sm text-ink-500">Компании из базы кейса: выберите клиента — профиль соберётся из данных банка автоматически</p>
        </div>
      </div>

      <CaseClients onOpen={(id) => open(id, "/")} />

      <h2 className="section-title">Открытые компании</h2>

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
                  <div className="mt-0.5 text-sm text-ink-500">{p.label ? p.label.replace(/^Компания [^:]+: /, "") : p.industry || "Отрасль не указана"}</div>
                </div>
                {current && (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-ink-900 px-2 py-0.5 text-xs font-medium text-white">
                    <Check size={12} /> Анализируем
                  </span>
                )}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                <span className="rounded-md bg-ink-100 px-2 py-0.5 text-ink-700">{p.client_id ? (p.is_demo ? "Демо-клиент кейса" : "Клиент из базы кейса") : p.is_demo ? "Встроенная" : "Добавлена вручную"}</span>
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
