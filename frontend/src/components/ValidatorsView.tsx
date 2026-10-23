import { useEffect, useState } from "react";
import { api } from "../api";
import type { ValidatorInfo } from "../types";

const GUARD_NAME: Record<string, string> = {
  input: "Input guard",
  tool_args: "Tool arguments",
  tool_result: "Tool results",
  proposal: "Structured decision",
  action: "Action guard",
};

export default function ValidatorsView() {
  const [rows, setRows] = useState<ValidatorInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.validators().then(setRows).catch((e: Error) => setError(e.message)); }, []);

  return (
    <section className="page" aria-labelledby="val-title">
      <header className="page-header">
        <div>
          <h2 id="val-title">Custom validators</h2>
          <p className="muted measure">
            Eight validators written for this project (<code>backend/app/validators.py</code>). The same validator can
            behave differently in different guards: <code>on_fail</code> is chosen where it's used.
          </p>
        </div>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="validators">
        {rows.map((v) => (
          <li key={v.name} className="validator">
            <h3>{v.name}</h3>
            <p className="muted small"><code>{v.registered_as}</code></p>
            <p>{v.description}</p>
            <p className="used">
              {v.used_in.map((u) => (
                <span key={u.guard} className="use">
                  {GUARD_NAME[u.guard] ?? u.guard}: <code>on_fail={u.on_fail}</code>
                </span>
              ))}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
