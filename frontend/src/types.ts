// Mirrors backend/app/schemas.py. Keep the two in sync.

export type ValidatorAction = "passed" | "fixed" | "reasked" | "unresolved" | "blocked" | "filtered" | "noted";

export interface LedgerEntry {
  validator: string;
  path: string;
  action: ValidatorAction;
  on_fail: string | null;
  before: unknown;
  after: unknown;
  message: string | null;
}

export interface GuardIteration {
  index: number;
  raw_output: string | null;
  entries: LedgerEntry[];
  reask_feedback: string | null;
}

export type GuardKind = "input" | "tool_args" | "tool_result" | "proposal" | "action";

export interface GuardRun {
  guard: GuardKind;
  label: string;
  passed: boolean;
  iterations: GuardIteration[];
  error: string | null;
  note: string | null;
}

export interface ToolStep {
  name: string;
  arguments: Record<string, unknown>;
  status: "ok" | "blocked" | "invalid";
  result: string;
  redacted: boolean;
}

export interface ActionRecord {
  kind: "refund" | "escalation";
  invoice_id: string | null;
  amount: number | null;
  status: "executed" | "pending_approval" | "failed" | "opened";
  approval_id: string | null;
  detail: string;
}

export type Status = "completed" | "pending_approval" | "escalated" | "blocked" | "failed";

export interface Proposal {
  category: string;
  summary: string;
  evidence: string[];
  decision: {
    refund?: { invoice_id: string; amount: number } | null;
    customer_reply: string;
    needs_human?: boolean;
  };
}

export interface RequestResult {
  id: string;
  patient_id: string;
  created_at: string;
  message: string;
  masked_message: string | null;
  status: Status;
  reply: string;
  proposal: Proposal | null;
  guard_runs: GuardRun[];
  tool_steps: ToolStep[];
  actions: ActionRecord[];
  security_events: string[];
  tainted: boolean;
  llm_calls: number;
  latency_ms: number;
}

export interface Invoice {
  id: string;
  service: string;
  date: string;
  amount: number;
  insurance_covered: number;
  paid: number;
  refunded: number;
  refundable: number;
}

export interface Approval {
  id: string;
  request_id: string;
  patient_id: string;
  invoice_id: string;
  amount: number;
  reason: string;
  status: "pending" | "approved" | "rejected" | "failed";
  created_at: string;
  decided_by: string | null;
  note: string | null;
  result: string | null;
}

export interface Person {
  id: string;
  name: string;
}

export interface Sample {
  id: string;
  title: string;
  patient_id: string;
  message: string;
  expect_status: Status;
  teaches: string;
}

export interface Health {
  status: string;
  llm_mode: string;
  model: string;
  auto_approve_limit: number;
  num_reasks: number;
}

export interface ValidatorInfo {
  name: string;
  registered_as: string;
  description: string;
  used_in: { guard: string; on_fail: string }[];
}

export interface Stats {
  total_requests: number;
  by_status: Record<string, number>;
  security_events: number;
  pending_approvals: number;
  refunded_total: number;
}
