import { useCallback, useEffect, useState } from "react";
import { api, setPatient, setStaff } from "./api";
import ApprovalsView from "./components/ApprovalsView";
import Composer from "./components/Composer";
import LogView from "./components/LogView";
import ResultView from "./components/ResultView";
import ValidatorsView from "./components/ValidatorsView";
import type { Health, Invoice, Person, RequestResult, Sample } from "./types";

type Tab = "desk" | "approvals" | "validators" | "log";

export default function App() {
  const [tab, setTab] = useState<Tab>("desk");
  const [health, setHealth] = useState<Health | null>(null);
  const [apiDown, setApiDown] = useState(false);
  const [patients, setPatients] = useState<Person[]>([]);
  const [staff, setStaffList] = useState<Person[]>([]);
  const [patientId, setPatientId] = useState("p-riya");
  const [staffId, setStaffId] = useState("staff-anita");
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [history, setHistory] = useState<RequestResult[]>([]);
  const [selected, setSelected] = useState<RequestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState(0);

  const refreshInvoices = useCallback(() => {
    api.invoices().then(setInvoices).catch(() => undefined);
    api.approvals().then((a) => setPendingCount(a.filter((x) => x.status === "pending").length)).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setApiDown(true));
    api.people().then((p) => { setPatients(p.patients); setStaffList(p.staff); }).catch(() => undefined);
    api.samples().then(setSamples).catch(() => undefined);
  }, []);

  useEffect(() => { setPatient(patientId); refreshInvoices(); }, [patientId, refreshInvoices]);
  useEffect(() => { setStaff(staffId); }, [staffId]);

  const submit = async (text: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.submit(text);
      setHistory((h) => [r, ...h]);
      setSelected(r);
      refreshInvoices();
    } catch (e) {
      setError(`Not sent: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const staffName = staff.find((s) => s.id === staffId)?.name ?? staffId;
  const modeLabel = health ? (health.llm_mode === "scripted" ? "Scripted LLM (offline demo)" : health.model) : "…";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">₹</span>
          <div>
            <h1>RefundDesk</h1>
            <p className="brand-sub">Sunrise Family Clinic billing, guarded by Guardrails AI · <span className="mode">{modeLabel}</span></p>
          </div>
        </div>
        <div className="topbar-right">
          <label className="picker">
            <span>Patient</span>
            <select value={patientId} onChange={(e) => setPatientId(e.target.value)}>
              {(patients.length ? patients : [{ id: "p-riya", name: "Riya Sharma" }]).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="picker">
            <span>Staff</span>
            <select value={staffId} onChange={(e) => setStaffId(e.target.value)}>
              {(staff.length ? staff : [{ id: "staff-anita", name: "Anita" }]).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <nav className="tabs" aria-label="Sections">
            {([["desk", "Desk"], ["approvals", `Approvals${pendingCount ? ` (${pendingCount})` : ""}`],
               ["validators", "Validators"], ["log", "Log"]] as [Tab, string][]).map(([id, label]) => (
              <button key={id} className={`tab${tab === id ? " is-active" : ""}`} aria-current={tab === id ? "page" : undefined}
                onClick={() => { setTab(id); refreshInvoices(); }}>{label}</button>
            ))}
          </nav>
        </div>
      </header>

      {apiDown && (
        <p className="banner" role="alert">
          The API isn't reachable. Start it with <code>uvicorn app.main:app --port 8000</code> in <code>backend/</code>,
          or run <code>docker compose up</code>.
        </p>
      )}

      <main>
        {tab === "desk" && (
          <div className="desk">
            <Composer invoices={invoices} samples={samples} history={history} selectedId={selected?.id ?? null}
              busy={busy} error={error} onSubmit={submit}
              onSelect={(id) => setSelected(history.find((h) => h.id === id) ?? null)} />
            <ResultView r={selected} />
          </div>
        )}
        {tab === "approvals" && <ApprovalsView staffName={staffName} onChanged={refreshInvoices} />}
        {tab === "validators" && <ValidatorsView />}
        {tab === "log" && (
          <LogView canReset={health?.llm_mode === "scripted"}
            onOpen={(r) => { setSelected(r); setTab("desk"); }}
            onReset={() => { setHistory([]); setSelected(null); refreshInvoices(); }} />
        )}
      </main>
    </div>
  );
}
