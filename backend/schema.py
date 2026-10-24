"""Pydantic models.

Two kinds:
  1. GUARDED models (RefundProposal, GetInvoiceArgs, RefundAction): the LLM's output and tool
     arguments. Validators are attached per field with json_schema_extra={"validators": [...]},
     and Guard.for_pydantic(Model) builds a guard from them.
  2. API models: what FastAPI returns to the React UI (keep in sync with frontend/src/types.ts).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .validators import (
    InvoiceBelongsToPatient, MaskPII, MaxChars, NoPaymentRedirect, QuotesFromMessage, ReplyMatchesRefund,
    WithinRefundableBalance, audit_and_block,
)

INVOICE_ID = r"^INV-\d{4}$"

# ======================= guarded models (LLM output and tool arguments) =======================

Category = Literal["duplicate_charge", "insurance_not_applied", "service_not_received", "overcharge",
                   "not_a_refund_request"]


class RefundLine(BaseModel):
    invoice_id: str = Field(
        pattern=INVOICE_ID, description="The invoice to refund, e.g. INV-1043",
        json_schema_extra={"validators": [InvoiceBelongsToPatient(on_fail=audit_and_block)]})
    amount: float = Field(gt=0, description="Refund amount in rupees")


class Decision(BaseModel):
    refund: Optional[RefundLine] = Field(
        default=None, description="The refund to issue, or null if no refund is due",
        json_schema_extra={"validators": [WithinRefundableBalance(on_fail="reask")]})
    customer_reply: str = Field(
        description="A short, polite reply to the patient (max 600 characters)",
        json_schema_extra={"validators": [MaskPII(on_fail="fix"), NoPaymentRedirect(on_fail="reask"),
                                          MaxChars(limit=600, on_fail="fix")]})
    needs_human: bool = Field(default=False, description="True if a staff member should review this case")


class RefundProposal(BaseModel):
    """What the LLM must return. Shape is checked by the JSON schema; meaning by the validators."""
    category: Category
    summary: str = Field(description="One-sentence summary of the request (max 240 characters)",
                         json_schema_extra={"validators": [MaskPII(on_fail="fix"), MaxChars(limit=240, on_fail="fix")]})
    evidence: List[str] = Field(default_factory=list,
                                description="Exact short quotes from the patient's message that support the decision",
                                json_schema_extra={"validators": [QuotesFromMessage(on_fail="fix")]})
    decision: Decision = Field(json_schema_extra={"validators": [ReplyMatchesRefund(on_fail="reask")]})


class GetInvoiceArgs(BaseModel):
    """Arguments of the get_invoice TOOL, validated by a guard before the tool runs."""
    invoice_id: str = Field(pattern=INVOICE_ID,
                            json_schema_extra={"validators": [InvoiceBelongsToPatient(on_fail=audit_and_block)]})


class RefundAction(BaseModel):
    """Arguments of the issue_refund ACTION. Re-validated right before money moves (also at approval time)."""
    refund: RefundLine = Field(json_schema_extra={"validators": [WithinRefundableBalance(on_fail="exception")]})


# ======================= API models =======================

class RequestIn(BaseModel):
    message: str = Field(min_length=1, max_length=1500)

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message is blank")
        return v.strip()


ValidatorAction = Literal["passed", "fixed", "reasked", "unresolved", "blocked", "filtered", "noted"]


class LedgerEntry(BaseModel):
    validator: str
    path: str                       # "$.decision.refund", "$" for a whole string
    action: ValidatorAction
    on_fail: str | None = None
    before: Any = None
    after: Any = None
    message: str | None = None


class GuardIteration(BaseModel):
    index: int
    raw_output: str | None = None
    entries: List[LedgerEntry] = []
    reask_feedback: str | None = None   # what Guardrails told the LLM before this attempt


class GuardRun(BaseModel):
    guard: Literal["input", "tool_args", "tool_result", "proposal", "action"]
    label: str
    passed: bool
    iterations: List[GuardIteration] = []
    error: str | None = None
    note: str | None = None


class ToolStep(BaseModel):
    name: str
    arguments: dict
    status: Literal["ok", "blocked", "invalid"]
    result: str = ""
    redacted: bool = False


class ActionRecord(BaseModel):
    kind: Literal["refund", "escalation"]
    invoice_id: str | None = None
    amount: float | None = None
    status: Literal["executed", "pending_approval", "failed", "opened"]
    approval_id: str | None = None
    detail: str = ""


Status = Literal["completed", "pending_approval", "escalated", "blocked", "failed"]


class RequestResult(BaseModel):
    id: str
    patient_id: str
    created_at: datetime
    message: str
    masked_message: str | None = None
    status: Status
    reply: str
    proposal: dict | None = None
    guard_runs: List[GuardRun] = []
    tool_steps: List[ToolStep] = []
    actions: List[ActionRecord] = []
    security_events: List[str] = []
    tainted: bool = False
    llm_calls: int = 0
    latency_ms: int = 0


class Invoice(BaseModel):
    id: str
    patient_id: str
    service: str
    date: str
    amount: float
    insurance_covered: float
    paid: float
    refunded: float
    refundable: float


class Approval(BaseModel):
    id: str
    request_id: str
    patient_id: str
    invoice_id: str
    amount: float
    reason: str
    status: Literal["pending", "approved", "rejected", "failed"]
    created_at: datetime
    decided_by: str | None = None
    note: str | None = None
    result: str | None = None


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=300)


class Person(BaseModel):
    id: str
    name: str


class Sample(BaseModel):
    id: str
    title: str
    patient_id: str
    message: str
    expect_status: Status
    teaches: str
