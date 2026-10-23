import { useCallback, useEffect, useState } from "react";
import { api, rupees, STATUS_TEXT } from "../api";
import type { RequestResult, Stats } from "../types";

export default function LogView({ onOpen, canReset, onReset }: {
  onOpen: (r: RequestResult) => void; canReset: boolean; onReset: () => void;
}) {
  const [rows, setRows] = useState<RequestResult[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api.requests(50), api.stats()])
      .then(([r, s]) => { setRows(r); setStats(s); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const reset = async () => {
    await api.reset();
    onReset();
    load();
  };

  return (
    <section className="page" aria-labelledby="log-title">
      <header className="page-header">
        <div>
          <h2 id="log-title">Log</h2>
          <p className="muted measure">Every request is stored in MongoDB with its full guard ledger.</p>
        </div>
        <div className="page-actions">
          <button className="btn-quiet" onClick={load}>Refresh</button>
          {canReset && <button className="btn-quiet" onClick={reset}>Reset demo data</button>}
        </div>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {stats && (
        <p className="stats-line">
          {stats.total_requests} requests, {stats.by_status.blocked ?? 0} blocked, {stats.pending_approvals} waiting for
          approval, {stats.security_events} security events, {rupees(stats.refunded_total)} refunded.
        </p>
      )}
      {rows.length === 0 ? (
        <p className="muted">No requests yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="log-table">
            <thead><tr><th scope="col">Time</th><th scope="col">Patient</th><th scope="col">Message</th><th scope="col">Outcome</th><th scope="col" className="num">LLM calls</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => onOpen(r)}>
                  <td className="nowrap">{new Date(r.created_at).toLocaleTimeString()}</td>
                  <td className="nowrap">{r.patient_id}</td>
                  <td>{r.message}</td>
                  <td className={`st-${r.status}`}>{STATUS_TEXT[r.status]}</td>
                  <td className="num">{r.llm_calls}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
