import { useEffect, useState } from "react";
import { getHealth } from "../api";
import { texts } from "../texts";

type Status = "checking" | "ok" | "down";

export function ServerStatus() {
  const [status, setStatus] = useState<Status>("checking");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    getHealth()
      .then((health) => {
        setStatus("ok");
        setDetail(`${health.companies.toLocaleString("ru-RU")}`);
      })
      .catch((error: Error) => {
        setStatus("down");
        setDetail(error.message);
      });
  }, []);

  const label = status === "ok" ? texts.server.ok : status === "down" ? texts.server.down : texts.server.checking;
  return <span className={`server-status server-${status}`} title={`${label}: ${detail}`} aria-label={label} />;
}
