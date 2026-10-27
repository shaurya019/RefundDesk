"""All Guardrails AI guards in one place, plus a helper that turns a guard's history into a ledger for the UI.

    input_guard        string guard on the patient's message: injection -> exception, PII -> fix (mask)
    tool_result_guard  string guard on tool output: injection -> fix (redact the offending lines)
    tool_args_guard    Guard.for_pydantic(GetInvoiceArgs): invoice must belong to the patient
    proposal_guard     Guard.for_pydantic(RefundProposal): the LLM's structured decision, with reasks
    action_guard       Guard.for_pydantic(RefundAction): re-checked right before money moves

Guards are built per request: Guard objects keep a call history, and a fresh guard keeps one
request's ledger separate from another's.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from guardrails import Guard

from .schemas import GetInvoiceArgs, GuardIteration, GuardRun, LedgerEntry, RefundAction, RefundProposal
from .validators import MaskPII, NoPromptInjection

# Guardrails wraps validators in OpenTelemetry spans even with metrics off; when a validator raises
# inside its thread pool, OTel logs a harmless "Failed to detach context" error. Keep logs readable.
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

# validator name -> on_fail, per guard (the same validator can behave differently in different guards)
ON_FAIL = {
    "input": {"NoPromptInjection": "exception", "MaskPII": "fix"},
    "tool_result": {"NoPromptInjection": "fix"},
    "tool_args": {"InvoiceBelongsToPatient": "custom: audit_and_block"},
    "proposal": {"InvoiceBelongsToPatient": "custom: audit_and_block", "WithinRefundableBalance": "reask",
                 "MaskPII": "fix", "NoPaymentRedirect": "reask", "MaxChars": "fix", "QuotesFromMessage": "fix",
                 "ReplyMatchesRefund": "reask"},
    "action": {"InvoiceBelongsToPatient": "custom: audit_and_block", "WithinRefundableBalance": "exception"},
}


def _quiet(guard: Guard) -> Guard:
    # Guardrails sends anonymous usage telemetry by default. Turn it off per guard
    # (or run `guardrails configure --disable-metrics` once, which writes ~/.guardrailsrc).
    guard.configure(allow_metrics_collection=False)
    return guard


def input_guard() -> Guard:
    return _quiet(Guard(name="input").use(NoPromptInjection(threshold=3, on_fail="exception"), MaskPII(on_fail="fix")))


def tool_result_guard() -> Guard:
    return _quiet(Guard(name="tool_result").use(NoPromptInjection(threshold=2, on_fail="fix")))


def tool_args_guard() -> Guard:
    return _quiet(Guard.for_pydantic(GetInvoiceArgs, name="tool_args"))


def proposal_guard() -> Guard:
    return _quiet(Guard.for_pydantic(RefundProposal, name="proposal"))


def action_guard() -> Guard:
    return _quiet(Guard.for_pydantic(RefundAction, name="action"))


# ---------------- ledger ----------------

def _plain(value: Any) -> Any:
    """Make values JSON-friendly for the UI (ReAsk objects become a short label)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if type(value).__name__.endswith("ReAsk"):
        return "(sent back to the LLM)"
    return str(value)


def _messages_text(messages: Any) -> str | None:
    if messages is None:
        return None
    out = []
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", m)
        out.append(str(getattr(content, "source", content)))
    return "\n".join(out)


def ledger(guard: Guard, kind: str, label: str, passed: bool, error: str | None = None,
           blocked_by: str | None = None) -> GuardRun:
    """Turn guard.history.last into a UI-friendly list of iterations and validator outcomes.

    blocked_by: when a validator raised (on_fail="exception" or our custom handler), Guardrails
    stops before logging it, so the caller tells us which validator it was."""
    on_fail = ON_FAIL.get(kind, {})
    run = GuardRun(guard=kind, label=label, passed=passed, error=error)
    try:
        call = guard.history.last
    except Exception:
        return run
    if call is None:
        return run
    iterations = list(call.iterations)
    for idx, it in enumerate(iterations):
        is_last = idx == len(iterations) - 1
        entries: list[LedgerEntry] = []
        for log in it.validator_logs or []:
            res = log.validation_result
            outcome = getattr(res, "outcome", None)
            failed = str(getattr(outcome, "value", outcome)).lower() == "fail"
            policy = on_fail.get(log.validator_name, "noop")
            if not failed:
                action = "passed"
            elif policy == "fix":
                action = "fixed"
            elif policy == "reask":
                action = "unresolved" if is_last else "reasked"
            elif policy in ("exception",) or policy.startswith("custom"):
                action = "blocked"
            elif policy == "filter":
                action = "filtered"
            else:
                action = "noted"
            entries.append(LedgerEntry(
                validator=log.validator_name, path=log.property_path or "$", action=action, on_fail=policy,
                before=_plain(log.value_before_validation),
                after=_plain(log.value_after_validation) if failed else None,
                message=getattr(res, "error_message", None) if failed else None))
        # JSON-schema failures (wrong enum, missing field, bad type) aren't validator logs.
        vr = getattr(it.outputs, "validation_response", None)
        if type(vr).__name__ == "SkeletonReAsk":
            msg = "; ".join(f.error_message or "" for f in vr.fail_results)
            entries.insert(0, LedgerEntry(validator="JSON schema (Pydantic)", path="$", on_fail="reask",
                                          action="unresolved" if is_last else "reasked", message=msg))
        if getattr(it, "error", None):
            if blocked_by and any(e.validator == blocked_by and e.action == "blocked" for e in entries):
                pass                                   # Guardrails already logged the failing validator
            elif blocked_by:
                entries.insert(0, LedgerEntry(validator=blocked_by, path="$", action="blocked",
                                              on_fail=on_fail.get(blocked_by, "exception"), message=error or str(it.error)))
            else:
                entries.insert(0, LedgerEntry(validator="JSON parsing", path="$", action="unresolved", message=str(it.error)))
        entries.sort(key=lambda e: (e.path, e.validator))
        feedback = None
        if idx > 0:
            # The reask message Guardrails sent: the previous JSON with each failing value wrapped in
            # {"incorrect_value": ..., "error_messages": [...]}. We show that part.
            text = _messages_text(getattr(it.inputs, "messages", None)) or ""
            start = text.find("I was given the following")
            end = text.find("Help me correct", start)
            feedback = text[start:end].strip()[:1500] if start != -1 else None
        run.iterations.append(GuardIteration(index=idx, raw_output=it.raw_output, entries=entries,
                                             reask_feedback=feedback))
    return run


def validators_catalog() -> list[dict]:
    """For the UI's Validators tab."""
    from . import validators as v
    rows = []
    for cls in [v.MaskPII, v.NoPromptInjection, v.MaxChars, v.NoPaymentRedirect, v.InvoiceBelongsToPatient,
                v.WithinRefundableBalance, v.QuotesFromMessage, v.ReplyMatchesRefund]:
        used = [{"guard": g, "on_fail": pol} for g, m in ON_FAIL.items() for name, pol in m.items() if name == cls.__name__]
        rows.append({"name": cls.__name__, "registered_as": getattr(cls, "rail_alias", ""),
                     "description": " ".join((cls.__doc__ or "").split()), "used_in": used})
    return rows


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
