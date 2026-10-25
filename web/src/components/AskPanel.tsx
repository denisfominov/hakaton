import { useEffect, useState } from "react";
import { askQuestion, getQuestions, type InsightAnswer } from "../api";
import { texts } from "../texts";
import { Claim, type OpenSource } from "./Claims";

const NO_KEY = "LLM_API_KEY";

type Props = { insightId: string; role: string; onOpen: OpenSource };

export function AskPanel({ insightId, role, onOpen }: Props) {
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<InsightAnswer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const t = texts.ask;

  useEffect(() => {
    getQuestions(insightId).then(setAnswers).catch(() => setAnswers([]));
  }, [insightId]);

  const ask = (text: string) => {
    const value = text.trim();
    if (value.length < 3 || busy) return;
    setBusy(true);
    setError("");
    askQuestion(insightId, value, role)
      .then((answer) => {
        setAnswers((list) => [...list, answer]);
        setQuestion("");
      })
      .catch((e: Error) => setError(e.message.includes(NO_KEY) ? t.noKey : e.message))
      .finally(() => setBusy(false));
  };

  const last = answers[answers.length - 1];
  const suggestions = last?.follow_up.length ? last.follow_up : t.examples;

  return (
    <section className="widget ask">
      <h3>{t.title}</h3>
      <p className="muted small">{t.hint}</p>
      {answers.length > 0 && (
        <ul className="answers">
          {answers.map((a) => (
            <li key={a.id}>
              <p className="answer-question">{a.question}</p>
              <p>{a.answer}</p>
              {!a.answerable && <p className="muted small">{t.unanswerable}</p>}
              {a.claims.length > 0 && <ul className="card-claims">{a.claims.map((c, i) => <Claim key={i} claim={c} onOpen={onOpen} />)}</ul>}
            </li>
          ))}
        </ul>
      )}
      <div className="chips">
        <span className="muted small">{last?.follow_up.length ? t.followUp : ""}</span>
        {suggestions.map((s) => <button key={s} className="chip chip-button" disabled={busy} onClick={() => ask(s)}>{s}</button>)}
      </div>
      <form className="ask-form" onSubmit={(e) => { e.preventDefault(); ask(question); }}>
        <input value={question} placeholder={t.placeholder} maxLength={1000} disabled={busy}
          onChange={(e) => setQuestion(e.target.value)} />
        <button className="action action-primary" disabled={busy || question.trim().length < 3}>{busy ? t.sending : t.send}</button>
      </form>
      {error && <p className="error-text">{t.failed}: {error}</p>}
    </section>
  );
}
