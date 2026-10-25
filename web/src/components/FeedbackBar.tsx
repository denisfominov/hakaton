import { useState } from "react";
import { sendFeedback, type FeedbackKind } from "../api";
import { texts } from "../texts";

type Props = { insightId: string; role: string; counts: Record<string, number> };

export function FeedbackBar({ insightId, role, counts: initial }: Props) {
  const [counts, setCounts] = useState(initial);
  const [message, setMessage] = useState("");
  const [hidden, setHidden] = useState((initial.hide ?? 0) > (initial.unhide ?? 0));
  const t = texts.feedback;

  const send = (kind: FeedbackKind) => {
    sendFeedback(insightId, kind, role)
      .then((result) => {
        setCounts(result.counts);
        if (kind === "hide" || kind === "unhide") setHidden(kind === "hide");
        setMessage(kind === "hide" ? t.hidden : kind === "unhide" ? "" : t.thanks);
      })
      .catch((error: Error) => setMessage(`${t.failed}: ${error.message}`));
  };

  return (
    <div className="feedback-bar">
      <span className="muted small">{t.question}</span>
      <button className="action" onClick={() => send("useful")}>{t.useful} · {counts.useful ?? 0}</button>
      <button className="action" onClick={() => send("not_useful")}>{t.notUseful} · {counts.not_useful ?? 0}</button>
      <button className="action" onClick={() => send(hidden ? "unhide" : "hide")}>{hidden ? t.unhide : t.hide}</button>
      {message && <span className="small">{message}</span>}
    </div>
  );
}
