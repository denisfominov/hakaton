import { useEffect, useState } from "react";
import { Shell, type Page } from "./components/Shell";
import { HomePage } from "./pages/HomePage";
import { InsightsPage } from "./pages/InsightsPage";

const pageFromHash = (): Page => (window.location.hash === "#/insights" ? "insights" : "home");

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (next: Page) => {
    window.location.hash = next === "home" ? "#/" : `#/${next}`;
  };

  return (
    <Shell page={page} onNavigate={navigate}>
      {page === "home" ? <HomePage onOpenInsights={() => navigate("insights")} /> : <InsightsPage onBack={() => navigate("home")} />}
    </Shell>
  );
}
