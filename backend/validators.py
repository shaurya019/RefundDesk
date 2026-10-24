"""Custom Guardrails AI validators.

A validator is a class with `_validate(value, metadata) -> PassResult | FailResult`.
  - `metadata` is whatever the caller passes to guard(..., metadata={...}): here, the
    patient's invoices and balances from MongoDB. That's how a validator checks facts
    the LLM can't be trusted with.
  - `FailResult(error_message=..., fix_value=...)`: error_message is shown to the LLM on a
    reask; fix_value is used when on_fail="fix".
  - `on_fail` is chosen where the validator is USED, not where it's defined, so one
    validator can block in one place and repair in another (see NoPromptInjection).

Docs: https://guardrailsai.com/docs/how_to_guides/custom_validators
      https://guardrailsai.com/docs/concepts/validator_on_fail_actions
"""
from __future__ import annotations

from typing import Any, Dict

from guardrails.validators import FailResult, PassResult, ValidationResult, Validator, register_validator

from . import detectors


class SecurityBlock(Exception):
    """Raised by the `audit_and_block` on_fail handler. The agent turns it into a blocked request + audit event."""

    def __init__(self, validator: str, value: Any, message: str):
        super().__init__(message)
        self.validator, self.value, self.message = validator, value, message


def audit_and_block(value: Any, fail_result: FailResult) -> Any:
    """A CUSTOM on_fail handler: Guardrails calls it with the failing value and the FailResult.

    Security failures shouldn't be reasked (the LLM would just learn which ids exist) or fixed
    (there's no safe fix). We raise, and the caller records an audit event.
    """
    raise SecurityBlock("InvoiceBelongsToPatient", value, fail_result.error_message or "blocked")


@register_validator(name="refunddesk/mask-pii", data_type="string")
class MaskPII(Validator):
    """Masks cards (Luhn-checked), Aadhaar, PAN, phones, emails and UPI ids. Use with on_fail='fix'."""

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        masked, kinds = detectors.mask_pii(str(value))
        if kinds:
            return FailResult(error_message=f"Contains personal data: {', '.join(kinds)}.", fix_value=masked)
        return PassResult()


@register_validator(name="refunddesk/no-prompt-injection", data_type="string")
class NoPromptInjection(Validator):
    """Weighted injection patterns. on_fail='exception' for user input; on_fail='fix' for tool
    results, where the fix removes only the offending lines (the rest of the data stays usable)."""

    def __init__(self, threshold: int = 3, on_fail: Any = None, **kwargs):
        super().__init__(on_fail=on_fail, threshold=threshold, **kwargs)
        self.threshold = threshold

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        score, hits = detectors.injection_score(str(value))
        if score < self.threshold:
            return PassResult()
        redacted, _ = detectors.redact_injected_lines(str(value), threshold=min(self.threshold, 2))
        return FailResult(error_message=f"Text contains instructions aimed at the assistant ({', '.join(hits)}).",
                          fix_value=redacted)


@register_validator(name="refunddesk/max-chars", data_type="string")
class MaxChars(Validator):
    def __init__(self, limit: int = 600, on_fail: Any = None, **kwargs):
        super().__init__(on_fail=on_fail, limit=limit, **kwargs)
        self.limit = limit

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        text = str(value)
        if len(text) <= self.limit:
            return PassResult()
        return FailResult(error_message=f"Must be at most {self.limit} characters (got {len(text)}).",
                          fix_value=text[: self.limit - 1].rstrip() + "…")


@register_validator(name="refunddesk/no-payment-redirect", data_type="string")
class NoPaymentRedirect(Validator):
    """Replies to patients must never ask for UPI ids/PINs, OTPs, bank details or contain links.
    This is the classic refund-scam pattern. Used with on_fail='reask' so the LLM rewrites the reply."""

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        m = detectors.PAYMENT_REDIRECT.search(str(value))
        if m:
            return FailResult(error_message=f"The reply mentions '{m.group(0)}'. Refunds go back to the original "
                                            "payment method automatically; never ask for payment details or links.")
        return PassResult()


@register_validator(name="refunddesk/invoice-belongs-to-patient", data_type="string")
class InvoiceBelongsToPatient(Validator):
    """The confused-deputy check: the invoice id must be one of THIS patient's invoices.
    metadata['patient_invoices'] comes from the database, never from the LLM."""

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        if value in set(metadata.get("patient_invoices", [])):
            return PassResult()
        return FailResult(error_message=f"Invoice {value} does not belong to this patient.")


@register_validator(name="refunddesk/within-refundable-balance", data_type="object")
class WithinRefundableBalance(Validator):
    """Object-level validator on {invoice_id, amount}: it needs both fields at once.

    No fix_value on purpose. When reasks run out, Guardrails applies an available fix_value and
    reports success. For money, silently capping an amount is a business decision, so we let it
    fail instead and route the request to a human.
    """

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        if value is None:
            return PassResult()
        if not isinstance(value, dict):          # a child field already failed (it's a ReAsk object)
            return PassResult()
        balance = metadata.get("balances", {}).get(value.get("invoice_id"))
        amount = value.get("amount")
        if balance is None or amount is None:
            return PassResult()                  # ownership/schema validators report those problems
        if amount > balance:
            return FailResult(error_message=f"Refund amount {amount:g} exceeds the refundable balance of "
                                            f"{balance:g} for invoice {value.get('invoice_id')}.")
        return PassResult()


@register_validator(name="refunddesk/quotes-from-message", data_type="list")
class QuotesFromMessage(Validator):
    """Provenance: every evidence quote must appear in the patient's (masked) message.
    The fix keeps only real quotes. (on_fail='filter' would drop the WHOLE list field.)"""

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        source = " ".join(str(metadata.get("source_message", "")).lower().split())
        quotes = [str(q) for q in (value or [])]
        kept = [q for q in quotes if " ".join(q.lower().split()) in source]
        if len(kept) == len(quotes):
            return PassResult()
        dropped = [q for q in quotes if q not in kept]
        return FailResult(error_message=f"These quotes are not in the patient's message: {dropped}", fix_value=kept)


@register_validator(name="refunddesk/reply-matches-refund", data_type="object")
class ReplyMatchesRefund(Validator):
    """Cross-field check on the whole decision: any amount the reply promises must equal the refund amount.
    (A root-level validator with reask crashes in guardrails-ai 0.11, so this lives on the `decision` object.)"""

    def _validate(self, value: Any, metadata: Dict) -> ValidationResult:
        if not isinstance(value, dict):
            return PassResult()
        refund = value.get("refund")
        reply = value.get("customer_reply")
        if not isinstance(reply, str) or (refund is not None and not isinstance(refund, dict)):
            return PassResult()                  # a child failed; its own reask comes first
        amount = (refund or {}).get("amount")
        wrong = [a for a in detectors.amounts_in(reply) if amount is None or abs(a - amount) > 0.01]
        if wrong:
            return FailResult(error_message=f"The reply mentions Rs {wrong[0]:g} but the refund amount is "
                                            f"{'none' if amount is None else f'Rs {amount:g}'}. They must match.")
        return PassResult()
