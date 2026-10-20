import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { Meta, Profile, Status } from "./types";

interface AppState {
  profiles: Profile[];
  profileId: string;
  profile: Profile | undefined;
  setProfileId: (id: string) => void;
  // роль пользователя: акценты интерпретации и действий (кейс: сервис для людей, а не для юрлиц)
  role: string;
  setRole: (role: string) => void;
  entryNote: string | null;
  reloadProfiles: () => Promise<void>;
  status: Status | null;
  reloadStatus: () => Promise<void>;
  meta: Meta | null;
  // меняется после обновления ленты/профиля, страницы по нему перезапрашивают данные
  dataVersion: number;
  bumpData: () => void;
  toast: (text: string, kind?: "ok" | "error") => void;
  bootError: string | null;
}

const Ctx = createContext<AppState | null>(null);

const STORAGE_KEY = "alpha.profileId";
const ROLE_KEY = "alpha.role";

function readStoredRole() {
  try {
    return localStorage.getItem(ROLE_KEY) || "cfo";
  } catch {
    return "cfo";
  }
}

function readStoredProfile() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function storeProfile(id: string) {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // приватный режим — просто не запоминаем
  }
}

export function AppProvider({ children, onToast }: { children: ReactNode; onToast: AppState["toast"] }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileIdState] = useState(readStoredProfile());
  const [status, setStatus] = useState<Status | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const [bootError, setBootError] = useState<string | null>(null);
  const [role, setRoleState] = useState(readStoredRole());
  const [entryNote, setEntryNote] = useState<string | null>(null);

  const setRole = (r: string) => {
    setRoleState(r);
    try {
      localStorage.setItem(ROLE_KEY, r);
    } catch {
      // приватный режим — роль не запоминаем
    }
  };

  const setProfileId = (id: string) => {
    setProfileIdState(id);
    storeProfile(id);
  };

  const reloadProfiles = useCallback(async () => {
    const list = await api.profiles();
    setProfiles(list);
    setProfileIdState((cur) => {
      const next = list.some((p) => p.id === cur) ? cur : list[0]?.id || "";
      storeProfile(next);
      return next;
    });
  }, []);

  const reloadStatus = useCallback(async () => {
    setStatus(await api.status());
  }, []);

  useEffect(() => {
    // вход из Альфа-Бизнеса: ?entry=<подписанный токен> -> компания и роль (СМОДЕЛИРОВАНО, docs/ALFA_BUSINESS_ENTRY.md)
    const params = new URLSearchParams(window.location.search);
    const token = params.get("entry");
    const enter = token
      ? api.entryVerify(token).then((r) => {
          storeProfile(r.profile.id);
          setProfileIdState(r.profile.id);
          setRole(r.role);
          setEntryNote(`Вход из Альфа-Бизнеса (макет): ${r.profile.name}`);
        }).catch((e) => setEntryNote(e.message)).finally(() => {
          params.delete("entry");
          const q = params.toString();
          window.history.replaceState(null, "", window.location.pathname + (q ? `?${q}` : ""));
        })
      : Promise.resolve();
    enter.then(() => Promise.all([reloadProfiles(), reloadStatus(), api.meta().then(setMeta)]))
      .then(() => setBootError(null))
      .catch((e) => setBootError(e.message));
  }, [reloadProfiles, reloadStatus]);

  const value: AppState = {
    profiles,
    profileId,
    profile: profiles.find((p) => p.id === profileId),
    setProfileId,
    role,
    setRole,
    entryNote,
    reloadProfiles,
    status,
    reloadStatus,
    meta,
    dataVersion,
    bumpData: () => setDataVersion((v) => v + 1),
    toast: onToast,
    bootError,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp outside AppProvider");
  return ctx;
}

// простой хук загрузки: data / loading / error + reload
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message || "Неизвестная ошибка"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, setData, loading, error, reload: () => setTick((t) => t + 1) };
}
