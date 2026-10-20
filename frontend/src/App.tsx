import { CheckCircle2, XCircle } from "lucide-react";
import { useCallback, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import Layout from "./components/Layout";
import { ErrorBox, Loading } from "./components/States";
import { AppProvider, useApp } from "./context";
import AboutPage from "./pages/AboutPage";
import BankPage from "./pages/BankPage";
import CompaniesPage from "./pages/CompaniesPage";
import DecisionsPage from "./pages/DecisionsPage";
import EventPage from "./pages/EventPage";
import FeedPage from "./pages/FeedPage";
import OverviewPage from "./pages/OverviewPage";
import PortfolioPage from "./pages/PortfolioPage";
import ProfilePage from "./pages/ProfilePage";

interface Toast {
  id: number;
  text: string;
  kind: "ok" | "error";
}

function Routed() {
  const { bootError, profileId } = useApp();
  const location = useLocation();
  if (bootError) {
    return (
      <div className="mx-auto max-w-xl py-20">
        <ErrorBox error={bootError} onRetry={() => window.location.reload()} />
        <p className="mt-4 text-sm text-ink-500">
          Backend запускается командой <code className="rounded bg-ink-100 px-1">uvicorn app.main:app --port 8000</code> в папке backend.
        </p>
      </div>
    );
  }
  if (!profileId) return <Loading text="Подключаемся к серверу…" />;
  return (
    <ErrorBoundary resetKey={location.pathname}>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/companies" element={<CompaniesPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/feed" element={<FeedPage />} />
        <Route path="/events/:id" element={<EventPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route path="/bank" element={<BankPage />} />
        <Route path="*" element={<div className="py-20 text-center text-ink-500">Страница не найдена. <Link to="/" className="underline">На главную</Link></div>} />
      </Routes>
    </ErrorBoundary>
  );
}

export default function App() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 6000 : 3500);
  }, []);

  return (
    <AppProvider onToast={toast}>
      <Layout>
        <Routed />
      </Layout>
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role="status"
            className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-lg ${
              t.kind === "error" ? "border-red-200 bg-red-50 text-red-800" : "border-ink-200 bg-white text-ink-900"}`}>
            {t.kind === "error" ? <XCircle size={16} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />}
            {t.text}
          </div>
        ))}
      </div>
    </AppProvider>
  );
}
