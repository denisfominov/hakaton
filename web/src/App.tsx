import { useEffect, useState } from "react";
import { getHealth, type Health } from "./api";
import { texts } from "./texts";

type State = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error"; message: string };

const number = new Intl.NumberFormat("ru-RU");

export default function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    getHealth()
      .then((health) => setState({ kind: "ok", health }))
      .catch((error: Error) => setState({ kind: "error", message: error.message }));
  }, []);

  return (
    <main className="page">
      <h1>{texts.title}</h1>
      {state.kind === "loading" && <p>{texts.checking}</p>}
      {state.kind === "ok" && (
        <section className="card">
          <p className="status status-ok">{texts.serverOk}</p>
          <ul>
            <li>{number.format(state.health.companies)} {texts.companies}</li>
            <li>{number.format(state.health.links)} {texts.links}</li>
            <li>{number.format(state.health.payments)} {texts.payments}</li>
          </ul>
        </section>
      )}
      {state.kind === "error" && (
        <section className="card">
          <p className="status status-error">{texts.serverDown}: {state.message}</p>
          <p className="hint">{texts.startHint}</p>
        </section>
      )}
    </main>
  );
}
