import { useCallback, useEffect, useState } from "react";
import { api, rupees } from "../api";
import type { Approval } from "../types";

export default function ApprovalsView({ staffName, onChanged }: { staffName: string; onChanged: () => void }) {
  const [items, setItems] = useState<Approval[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.approvals().then(setItems).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const decide = async (a: Approval, approve: boolean) => {
    setBusy(a.id);
    setError(null);
    try {
      const res = approve ? await api.approve(a.id, notes[a.id] ?? "") : await api.reject(a.id, notes[a.id] ?? "");
      setMessage(`${a.invoice_id}: ${res.result ?? res.status}`);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
      load();
    }
  };

  const pending = items.filter((a) => a.status === "pending");
  const decided = items.filter((a) => a.status !== "pending");

  return (
    <section className="page" aria-labelledby="ap-title">
      <header className="page-header">
        <div>
          <h2 id="ap-title">Approvals</h2>
          <p className="muted measure">
            Refunds above the auto-approve limit, or from requests where untrusted data was removed, wait here. Approving
            re-runs the action guard against today's balances before any money moves. You're acting as {staffName}.
          </p>
        </div>
        <button className="btn-quiet" onClick={load}>Refresh</button>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="ok" role="status">{message}</p>}

      <h3 className="sub">Waiting ({pending.length})</h3>
      {pending.length === 0 ? (
        <p className="muted">Nothing waiting. Try the “Insurance not applied” example on the Desk.</p>
      ) : (
        <ul className="approvals">
          {pending.map((a) => (
            <li key={a.id} className="approval">
              <div className="approval-main">
                <p className="approval-what">{rupees(a.amount)} on <code>{a.invoice_id}</code> for {a.patient_id}</p>
                <p className="muted small">Why it's here: {a.reason}</p>
                <label className="note">
                  <span className="sr-only">Note</span>
                  <input value={notes[a.id] ?? ""} placeholder="Note (optional)" maxLength={300}
                    onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
                </label>
              </div>
              <div className="approval-actions">
                <button className="btn" disabled={busy === a.id} onClick={() => decide(a, true)}>Approve refund</button>
                <button className="btn-quiet" disabled={busy === a.id} onClick={() => decide(a, false)}>Reject</button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {decided.length > 0 && (
        <>
          <h3 className="sub">Decided</h3>
          <div className="table-wrap">
            <table className="log-table">
              <thead><tr><th scope="col">Invoice</th><th scope="col" className="num">Amount</th><th scope="col">Status</th><th scope="col">By</th><th scope="col">Result</th></tr></thead>
              <tbody>
                {decided.map((a) => (
                  <tr key={a.id}>
                    <td><code>{a.invoice_id}</code></td>
                    <td className="num">{rupees(a.amount)}</td>
                    <td className={`st-${a.status}`}>{a.status}</td>
                    <td>{a.decided_by}</td>
                    <td>{a.result}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
