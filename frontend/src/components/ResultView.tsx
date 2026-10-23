import { rupees, STATUS_TEXT } from "../api";
import type { GuardRun, RequestResult } from "../types";
import GuardRunView from "./Ledger";

function Bill({ r }: { r: RequestResult }) {
  const p = r.proposal;
  if (!p) return null;
  const refund = p.decision.refund;
  return (
    <section className="bill" aria-labelledby="bill-title">
      <h3 id="bill-title">Validated decision</h3>
      <dl>
        <dt>Category</dt><dd>{p.category.replace(/_/g, " ")}</dd>
        <dt>Summary</dt><dd>{p.summary}</dd>
        <dt>Evidence</dt>
        <dd>{p.evidence.length ? p.evidence.map((q) => <q key={q}>{q}</q>) : <span className="muted">none</span>}</dd>
        <dt>Refund</dt>
        <dd className="bill-amount">{refund ? `${rupees(refund.amount)} on ${refund.invoice_id}` : "No refund"}</dd>
        <dt>Needs a human</dt><dd>{p.decision.needs_human ? "Yes" : "No"}</dd>
      </dl>
    </section>
  );
}

export default function ResultView({ r }: { r: RequestResult | null }) {
  if (!r) {
    return (
      <section className="result result-empty">
        <h2>The guard ledger</h2>
        <p className="muted measure">
          Send a request, or pick one of the examples. Every guard the request passes through is listed here, in order:
          the input guard, each tool call and its result, every attempt the LLM made at the structured decision, and the
          final check before money moves.
        </p>
      </section>
    );
  }
  const runs = r.guard_runs;
  const input = runs.filter((g) => g.guard === "input");
  const argRuns = runs.filter((g) => g.guard === "tool_args");
  const resultRuns = runs.filter((g) => g.guard === "tool_result");
  const proposal = runs.filter((g) => g.guard === "proposal");
  const action = runs.filter((g) => g.guard === "action");
  let ai = 0, ri = 0;

  return (
    <section className="result" aria-labelledby="result-title">
      <header className={`outcome outcome-${r.status}`}>
        <p className="outcome-status" id="result-title">{STATUS_TEXT[r.status]}</p>
        <p className="outcome-meta">
          {r.llm_calls} LLM {r.llm_calls === 1 ? "call" : "calls"} · {(r.latency_ms / 1000).toFixed(2)} s
          {r.tainted ? " · untrusted data was removed" : ""}
        </p>
        <blockquote className="reply">{r.reply}</blockquote>
        {r.actions.map((a, i) => (
          <p key={i} className={`action action-${a.status}`}>
            {a.kind === "refund"
              ? `Refund ${rupees(a.amount)} on ${a.invoice_id}: ${a.status.replace("_", " ")}`
              : "Escalation opened"}
            {a.detail ? `. ${a.detail}` : ""}
          </p>
        ))}
        {r.security_events.length > 0 && (
          <ul className="security">
            {r.security_events.map((s, i) => <li key={i}>Security event logged: {s}</li>)}
          </ul>
        )}
      </header>

      <ol className="pipeline">
        <li>
          <h3 className="step-title">Patient's message</h3>
          <p className="message">{r.message}</p>
          {r.masked_message && r.masked_message !== r.message && (
            <p className="message message-masked"><span className="muted">The LLM saw: </span>{r.masked_message}</p>
          )}
          {input.map((g, i) => <GuardRunView key={i} run={g} />)}
        </li>

        {r.tool_steps.length > 0 && (
          <li>
            <h3 className="step-title">Agent lookups</h3>
            {r.tool_steps.map((t, i) => {
              const runsHere: GuardRun[] = [];
              if (t.name === "get_invoice") {
                if (argRuns[ai]) runsHere.push(argRuns[ai++]);
                if (t.status === "ok" && resultRuns[ri]) runsHere.push(resultRuns[ri++]);
              }
              return (
                <div className="tool" key={i}>
                  <p className="tool-call">
                    <code>{t.name}({Object.entries(t.arguments).map(([k, v]) => `${k}=${String(v)}`).join(", ")})</code>
                    <span className={`tool-status tool-${t.status}`}>{t.status}</span>
                    {t.redacted && <span className="stamp stamp-fixed">Redacted</span>}
                  </p>
                  {runsHere.map((g, j) => <GuardRunView key={j} run={g} />)}
                  <details className="raw" open={t.redacted}>
                    <summary>What the LLM received</summary>
                    <pre className="code">{t.result}</pre>
                  </details>
                </div>
              );
            })}
          </li>
        )}

        {proposal.length > 0 && (
          <li>
            <h3 className="step-title">Structured decision</h3>
            {proposal.map((g, i) => <GuardRunView key={i} run={g} />)}
            <Bill r={r} />
          </li>
        )}

        {action.length > 0 && (
          <li>
            <h3 className="step-title">Before money moves</h3>
            {action.map((g, i) => <GuardRunView key={i} run={g} />)}
          </li>
        )}
      </ol>
    </section>
  );
}
