import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import FactsPanel from "../components/FactsPanel";
import Modal from "../components/Modal";
import { Empty, Loading } from "../components/States";
import { useApp } from "../context";

// C20.7: профиль только из набора данных Альфа-Банка — ручного ввода, шаблонов отраслей и подсказок нет
export default function ProfilePage() {
  const { profile, profiles, reloadProfiles, reloadStatus, bumpData, toast } = useApp();
  const navigate = useNavigate();
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (!profiles.length) return <Loading />;
  if (!profile) return <Empty title="Компания не выбрана" text="Выберите клиента на странице «Выбор компании»." />;

  const remove = async () => {
    try {
      await api.deleteProfile(profile.id);
      setConfirmDelete(false);
      await reloadProfiles();
      await reloadStatus();
      bumpData();
      toast("Компания убрана из списка");
      navigate("/companies");
    } catch (err: any) {
      toast(err.message, "error");
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Профиль компании</h1>
          <p className="mt-1 text-sm text-ink-500">{profile.label || profile.name}</p>
        </div>
        <button type="button" className="btn-secondary !text-red-700" onClick={() => setConfirmDelete(true)}
          disabled={profiles.length <= 1}>
          <Trash2 size={15} /> Убрать из списка
        </button>
      </div>

      <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        Сведения о компании берутся только из набора данных Альфа-Банка: отрасль по ОКВЭД, масштаб, место по выручке в
        выборке, группа, продукты банка, ВЭД, география, связи по платежам. Новости, сайты, внешние базы и знания модели
        профиль не дополняют; чего нет в данных — помечено «нет данных». Правка профиля вручную отключена.
      </div>

      {profile.client_id ? <FactsPanel profileId={profile.id} />
        : <Empty title="Нет данных в наборе банка" text="Для этой компании в наборе данных Альфа-Банка записи нет." />}

      {confirmDelete && (
        <Modal title="Убрать компанию из списка?" onClose={() => setConfirmDelete(false)}>
          <p className="text-sm text-ink-700">«{profile.name}», её избранное и кэш анализа будут удалены. Действия в плане
            останутся. Вернуть клиента можно на странице «Выбор компании».</p>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="btn-secondary" onClick={() => setConfirmDelete(false)}>Отмена</button>
            <button type="button" className="btn-primary !bg-red-600 hover:!bg-red-700" onClick={remove}>Убрать</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
