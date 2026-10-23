import { useState, type FormEvent, type KeyboardEvent } from "react";
import { rupees, STATUS_TEXT } from "../api";
import type { Invoice, RequestResult, Sample } from "../types";

const MAX = 1500;

interface Props {
  invoices: Invoice[];
  samples: Sample[];
  history: RequestResult[];
  selectedId: string | null;
  busy: boolean;
  error: string | null;
  onSubmit: (text: string) => void;
  onSelect: (id: string) => void;
}

export default function Composer({ invoices, samples, history, selectedId, busy, error, onSubmit, onSelect }: Props) {
  const [draft, setDraft] = useState("");

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = draft.trim();
    if (!t || busy || t.length > MAX) return;
    onSubmit(t);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
  };

  return (
    <aside className="composer-col">
      <section aria-labelledby="inv-title">
        <h2 id="inv-title">Your invoices</h2>
        <table className="invoices">
          <thead><tr><th scope="col">Invoice</th><th scope="col">Service</th><th scope="col" className="num">Refundable</th></tr></thead>
          <tbody>
            {invoices.map((i) => (
              <tr key={i.id}>
                <td><code>{i.id}</code></td>
                <td>{i.service}<span className="muted small"> · paid {rupees(i.paid)}</span></td>
                <td className="num">{rupees(i.refundable)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <form className="compose" onSubmit={submit}>
        <label htmlFor="msg"><h2>Write to the billing desk</h2></label>
        <textarea id="msg" rows={4} value={draft} placeholder="Describe your billing problem…"
          onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} />
        <div className="compose-row">
          <span className={`count${draft.length > MAX ? " over" : ""}`}>{draft.length}/{MAX}</span>
          <button className="btn" type="submit" disabled={busy || !draft.trim() || draft.length > MAX}>
            {busy ? "Checking…" : "Send request"}
          </button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </form>

      <section aria-labelledby="ex-title">
        <h2 id="ex-title">Examples</h2>
        <ul className="samples">
          {samples.map((s) => (
            <li key={s.id}>
              <button className="sample" disabled={busy} onClick={() => setDraft(s.message)} title={s.teaches}>
                <span className="sample-title">{s.title}</span>
                <span className="sample-teaches">{s.teaches}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="muted small">Clicking an example fills the box. Some examples are for the other patient; switch patients at the top.</p>
      </section>

      {history.length > 0 && (
        <section aria-labelledby="hist-title">
          <h2 id="hist-title">This session</h2>
          <ul className="history">
            {history.map((r) => (
              <li key={r.id}>
                <button className={`hist${r.id === selectedId ? " is-active" : ""}`} onClick={() => onSelect(r.id)}>
                  <span className={`dot dot-${r.status}`} aria-hidden="true" />
                  <span className="hist-text">{r.message}</span>
                  <span className="hist-status">{STATUS_TEXT[r.status]}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
