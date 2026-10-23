import type {
  Approval, Health, Invoice, Person, RequestResult, Sample, Stats, ValidatorInfo,
} from "./types";

// Demo identity: the pickers set these and every request carries them as headers.
let patientId = "p-riya";
let staffId = "staff-anita";
export const setPatient = (id: string) => { patientId = id; };
export const setStaff = (id: string) => { staffId = id; };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Patient-Id": patientId, "X-Staff-Id": staffId,
      ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  people: () => request<{ patients: Person[]; staff: Person[] }>("/api/people"),
  invoices: () => request<Invoice[]>("/api/invoices"),
  submit: (message: string) => request<RequestResult>("/api/requests", { method: "POST", body: JSON.stringify({ message }) }),
  requests: (limit = 30) => request<RequestResult[]>(`/api/requests?limit=${limit}`),
  requestById: (id: string) => request<RequestResult>(`/api/requests/${id}`),
  approvals: () => request<Approval[]>("/api/approvals"),
  approve: (id: string, note: string) =>
    request<Approval>(`/api/approvals/${id}/approve`, { method: "POST", body: JSON.stringify({ note }) }),
  reject: (id: string, note: string) =>
    request<Approval>(`/api/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({ note }) }),
  validators: () => request<ValidatorInfo[]>("/api/validators"),
  samples: () => request<Sample[]>("/api/samples"),
  stats: () => request<Stats>("/api/stats"),
  reset: () => request<{ status: string }>("/api/demo/reset", { method: "POST" }),
};

export const rupees = (n: number | null | undefined) =>
  n == null ? "–" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

export const STATUS_TEXT: Record<string, string> = {
  completed: "Completed",
  pending_approval: "Waiting for staff approval",
  escalated: "Escalated to a human",
  blocked: "Blocked by a guard",
  failed: "Failed",
};
