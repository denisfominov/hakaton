import { useEffect, useState } from "react";
import { Shell, type Page } from "./components/Shell";
import { HomePage } from "./pages/HomePage";
import { InsightPage } from "./pages/InsightPage";
import { InsightsPage } from "./pages/InsightsPage";

type Route = { page: Page; insightId?: string };

const INSIGHT = /^#\/insight\/([\w-]+)$/;

function routeFromHash(): Route {
  const hash = window.location.hash;
  const insight = hash.match(INSIGHT);
  if (insight) return { page: "insights", insightId: insight[1] };
  return { page: hash === "#/insights" ? "insights" : "home" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash);

  useEffect(() => {
    const onHash = () => {
      setRoute(routeFromHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (next: Page) => {
    window.location.hash = next === "home" ? "#/" : `#/${next}`;
  };

  return (
    <Shell page={route.page} onNavigate={navigate}>
      {route.page === "home" && <HomePage onOpenInsights={() => navigate("insights")} />}
      {route.page === "insights" && !route.insightId && <InsightsPage />}
      {route.insightId && <InsightPage insightId={route.insightId} onBack={() => navigate("insights")} />}
    </Shell>
  );
}
