import { useState } from "react";
import type { GuardRun, LedgerEntry } from "../types";

const STAMP: Record<string, string> = {
  passed: "Passed",
  fixed: "Fixed",
  reasked: "Reasked",
  unresolved: "Still failing",
  blocked: "Blocked",
  filtered: "Filtered",
  noted: "Noted",
};

export function Stamp({ action }: { action: string }) {
  return <span className={`stamp stamp-${action}`}>{STAMP[action] ?? action}</span>;
}

function show(v: unknown): string {
  if (v == null) return "null";
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 1);
}

type DiffLine = { kind: "same" | "removed" | "added"; text: string };

/** Line diff (longest common subsequence). Small inputs only: tool results and replies. */
function lineDiff(a: string, b: string): DiffLine[] {
  const x = a.split("\n"), y = b.split("\n");
  const n = x.length, m = y.length;
  const L: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { out.push({ kind: "same", text: x[i] }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ kind: "removed", text: x[i++] });
    else out.push({ kind: "added", text: y[j++] });
  }
  while (i < n) out.push({ kind: "removed", text: x[i++] });
  while (j < m) out.push({ kind: "added", text: y[j++] });
  return out;
}

function FixDiff({ before, after }: { before: unknown; after: unknown }) {
  // Multi-line text (a tool result): show which lines changed, unchanged lines stay plain.
  if (typeof before === "string" && typeof after === "string" && (before.includes("\n") || after.includes("\n"))) {
    return (
      <div className="line-diff" aria-label="Changes made by the fix">
        {lineDiff(before, after).map((l, k) => (
          <div key={k} className={`ld ld-${l.kind}`}>
            <span className="ld-mark" aria-hidden="true">{l.kind === "removed" ? "−" : l.kind === "added" ? "+" : " "}</span>
            <span className="sr-only">{l.kind === "removed" ? "Removed: " : l.kind === "added" ? "Added: " : ""}</span>
            {l.text || " "}
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="entry-diff">
      <span className="diff-label">Before</span><span className="diff-before">{show(before)}</span>
      <span className="diff-label">After</span><span className="diff-after">{show(after)}</span>
    </div>
  );
}

function EntryRow({ e }: { e: LedgerEntry }) {
  const failed = e.action !== "passed";
  return (
    <li className={`entry${failed ? " entry-failed" : ""}`}>
      <div className="entry-head">
        <code className="entry-path">{e.path}</code>
        <span className="entry-validator">{e.validator}</span>
        {e.on_fail && <span className="entry-onfail">on_fail={e.on_fail}</span>}
        <Stamp action={e.action} />
      </div>
      {failed && e.message && <p className="entry-message">{e.message}</p>}
      {e.action === "fixed" && <FixDiff before={e.before} after={e.after} />}
    </li>
  );
}

export default function GuardRunView({ run }: { run: GuardRun }) {
  const [showPassed, setShowPassed] = useState(false);
  const many = run.iterations.length > 1;
  return (
    <section className={`guard guard-${run.guard} ${run.passed ? "guard-ok" : "guard-stop"}`}>
      <header className="guard-head">
        <h3>{run.label}</h3>
        <span className="guard-verdict">{run.passed ? "Passed" : "Stopped"}</span>
      </header>
      {run.error && <p className="guard-error">{run.error}</p>}
      {run.note && <p className="guard-note">{run.note}</p>}
      {run.iterations.map((it) => {
        const failed = it.entries.filter((e) => e.action !== "passed");
        const passed = it.entries.filter((e) => e.action === "passed");
        return (
          <div className="attempt" key={it.index}>
            {many && <p className="attempt-title">Attempt {it.index + 1}{it.index > 0 ? " (after reask)" : ""}</p>}
            {it.reask_feedback && (
              <details className="raw">
                <summary>What Guardrails sent back to the LLM</summary>
                <pre className="code">{it.reask_feedback}</pre>
              </details>
            )}
            {failed.length > 0 ? (
              <ul className="entries">{failed.map((e, i) => <EntryRow e={e} key={i} />)}</ul>
            ) : (
              it.entries.length > 0 && <p className="all-passed">{it.entries.length === 1 ? "The 1 check passed." : `All ${it.entries.length} checks passed.`}</p>
            )}
            {passed.length > 0 && failed.length > 0 && (
              <button className="link" onClick={() => setShowPassed(!showPassed)}>
                {showPassed ? "Hide" : "Show"} {passed.length} passed {passed.length === 1 ? "check" : "checks"}
              </button>
            )}
            {(showPassed || failed.length === 0) && passed.length > 0 && failed.length > 0 && (
              <ul className="entries entries-passed">{passed.map((e, i) => <EntryRow e={e} key={i} />)}</ul>
            )}
            {failed.length === 0 && passed.length > 0 && (
              <details className="raw">
                <summary>Checks that ran</summary>
                <ul className="entries entries-passed">{passed.map((e, i) => <EntryRow e={e} key={i} />)}</ul>
              </details>
            )}
            {it.raw_output && run.guard === "proposal" && (
              <details className="raw">
                <summary>Raw LLM output</summary>
                <pre className="code">{prettyJson(it.raw_output)}</pre>
              </details>
            )}
          </div>
        );
      })}
    </section>
  );
}

function prettyJson(s: string) {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}
