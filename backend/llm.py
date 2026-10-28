"""LLM adapters.

Two calls are needed:
  chat(messages, tools)   one agent step with OpenAI function calling (tool lookup phase)
  json(messages=...)      returns a JSON string; passed to Guardrails as `llm_api`, so Guardrails
                          can call it again with its own reask messages when validation fails

OpenAILLM talks to the real API. ScriptedLLM is a deterministic stand-in that behaves like a
plausible (and sometimes wrong) model, so the whole app, UI included, runs and can be tested
without an API key. The guards don't know which one is in use.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str      # raw JSON string, exactly as the model produced it


@dataclass
class AssistantTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    calls: int

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...
    def json(self, *, messages: list[dict], **kwargs: Any) -> str: ...


class OpenAILLM:
    def __init__(self, api_key: str, model: str, reasoning_effort: str = ""):
        self.client = OpenAI(api_key=api_key, timeout=60, max_retries=2)
        self.model = model
        self.extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls += 1
        resp = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools,
                                                   max_completion_tokens=1500, **self.extra)
        msg = resp.choices[0].message
        calls = [ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
                 for c in (msg.tool_calls or []) if c.type == "function"]
        return AssistantTurn(content=msg.content or "", tool_calls=calls)

    def json(self, *, messages: list[dict], **kwargs: Any) -> str:
        # Guardrails passes extra kwargs (e.g. temperature). Reasoning models reject temperature,
        # so we ignore them. json_object mode guarantees parseable JSON; the guard checks the rest.
        self.calls += 1
        resp = self.client.chat.completions.create(model=self.model, messages=messages,
                                                   response_format={"type": "json_object"},
                                                   max_completion_tokens=2000, **self.extra)
        return resp.choices[0].message.content or ""


# =============================== ScriptedLLM ===============================

INVOICE_RX = re.compile(r"\bINV-\d{4}\b", re.IGNORECASE)


def _user_text(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user" and "<patient_message>" in str(m.get("content", "")):
            return str(m["content"]).split("<patient_message>")[1].split("</patient_message>")[0].strip()
    return ""


def _tool_texts(messages: list[dict]) -> list[str]:
    """Tool results, either as `tool` messages (agent loop) or the flattened lookup note (final JSON call)."""
    return [str(m.get("content", "")) for m in messages
            if m.get("role") == "tool" or str(m.get("content", "")).startswith("Invoice lookups")]


def _invoice_facts(text: str) -> dict:
    facts: dict[str, Any] = {}
    for key in ("invoice", "refundable", "insurance_covered", "paid", "amount"):
        m = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
        if m:
            facts[key] = m.group(1).strip()
    return facts


class ScriptedLLM:
    """A deterministic fake model for demos and tests. NOT a real LLM.

    It plays a helpful but fallible agent: it looks up the invoice the patient mentions, then
    drafts a proposal. On some inputs it deliberately makes the mistakes the guards exist for
    (overpaying, promising the wrong amount, asking for a UPI id, inventing a quote, trying
    another patient's invoice) and fixes them when Guardrails reasks.
    """

    def __init__(self) -> None:
        self.calls = 0

    # ---------- agent step ----------
    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        self.calls += 1
        if _tool_texts(messages):
            return AssistantTurn(content="I have what I need.")
        text = _user_text(messages)
        ids = INVOICE_RX.findall(text)
        if ids:
            return AssistantTurn(tool_calls=[ToolCall(id="call_1", name="get_invoice",
                                                      arguments=json.dumps({"invoice_id": ids[0].upper()}))])
        if re.search(r"refund|charged|bill|insurance|paid", text, re.IGNORECASE):
            return AssistantTurn(tool_calls=[ToolCall(id="call_1", name="list_my_invoices", arguments="{}")])
        return AssistantTurn(content="No lookup needed.")

    # ---------- structured output (Guardrails llm_api) ----------
    def json(self, *, messages: list[dict], **kwargs: Any) -> str:
        self.calls += 1
        all_text = "\n".join(str(m.get("content", "")) for m in messages)
        is_reask = "previous response" in all_text.lower() or "error_messages" in all_text.lower() \
            or "incorrect_value" in all_text.lower()
        original = messages if not is_reask else None
        return json.dumps(self._reask_answer(all_text) if is_reask else self._first_answer(original))

    def _context(self, messages: list[dict]) -> tuple[str, dict, bool]:
        text = _user_text(messages)
        tool_text = "\n".join(_tool_texts(messages))
        facts = _invoice_facts(tool_text)
        blocked = "BLOCKED" in tool_text
        return text, facts, blocked

    def _first_answer(self, messages: list[dict]) -> dict:
        text, facts, blocked = self._context(messages)
        low = text.lower()
        inv_ids = [i.upper() for i in INVOICE_RX.findall(text)]
        invoice = facts.get("invoice") or (inv_ids[0] if inv_ids else None)
        refundable = float(facts.get("refundable", "0") or 0)
        asked = re.search(r"(?:rs\.?|₹)\s*([0-9][0-9,]*)", low)
        asked_amount = float(asked.group(1).replace(",", "")) if asked else None
        quote = next((q for q in ("charged twice", "cashless was not applied", "not applied", "paid twice",
                                  "double charge") if q in low), None)
        evidence = [quote] if quote else []

        if not re.search(r"refund|charged|insurance|cashless|paid twice|double", low):
            return {"category": "not_a_refund_request", "summary": "General question, no refund requested.",
                    "evidence": [], "decision": {"refund": None, "needs_human": False,
                                                 "customer_reply": "Thanks for reaching out. For general questions "
                                                 "please call the front desk on 080-4567-1200."}}

        category = "insurance_not_applied" if "insurance" in low or "cashless" in low else "duplicate_charge"
        if blocked and invoice:
            # The lookup was refused (not this patient's invoice) but the model tries anyway.
            return {"category": category, "summary": f"Patient asks for a refund on {invoice}.",
                    "evidence": evidence,
                    "decision": {"refund": {"invoice_id": invoice, "amount": asked_amount or 1000},
                                 "customer_reply": "We'll process your refund.", "needs_human": False}}

        amount = asked_amount if asked_amount else refundable
        if amount <= 0:
            amount = float(facts.get("amount", "0") or 0)           # mistake: refunds a fully used service
        reply = f"Sorry about this. We will refund Rs {amount:g} to your original payment method within 5 working days."
        if "upi" in low:
            reply = "Sorry about this. Please share your UPI ID and we will send the refund there right away."
        if "skin" in low:
            evidence = evidence + ["the receptionist admitted the mistake"]   # not in the message
        return {"category": category, "summary": f"Patient reports {category.replace('_', ' ')} on {invoice}.",
                "evidence": evidence or ["refund"],
                "decision": {"refund": {"invoice_id": invoice, "amount": amount} if invoice else None,
                             "customer_reply": reply, "needs_human": False}}

    def _reask_answer(self, all_text: str) -> dict:
        """Guardrails' reask message contains the previous JSON in which every failing value is replaced
        by {"incorrect_value": ..., "error_messages": [...]}. Read it, then correct what was reported."""
        start = all_text.find("{", all_text.find("I was given the following JSON response"))
        try:
            prev, _ = json.JSONDecoder().raw_decode(all_text[start:])
        except (json.JSONDecodeError, ValueError):
            prev = {}
        errors: list[str] = []

        def unwrap(node: Any) -> Any:
            if isinstance(node, dict):
                if "incorrect_value" in node:
                    errors.extend(str(e) for e in node.get("error_messages", []))
                    return unwrap(node["incorrect_value"])
                return {k: unwrap(v) for k, v in node.items()}
            if isinstance(node, list):
                return [unwrap(v) for v in node]
            return node

        prev = unwrap(prev) if isinstance(prev, dict) else {}
        err = " ".join(errors)
        decision = dict(prev.get("decision") or {})
        refund = decision.get("refund") if isinstance(decision.get("refund"), dict) else None
        bal = re.search(r"refundable balance of ([0-9.]+)", err)
        if refund and bal:
            balance = float(bal.group(1))
            if balance <= 0:
                refund, decision["needs_human"] = None, True
            else:
                refund = {**refund, "amount": balance}
        decision["refund"] = refund
        amt = refund["amount"] if refund else None
        if amt:
            decision["customer_reply"] = (f"Sorry about this. We will refund Rs {amt:g} to your original payment "
                                          "method within 5 working days.")
        else:
            decision["customer_reply"] = ("Thanks for writing in. Our records don't show a refundable amount, so a "
                                          "member of our billing team will review this and get back to you.")
        decision.setdefault("needs_human", False)
        return {"category": prev.get("category", "overcharge"), "summary": prev.get("summary", "Refund request."),
                "evidence": prev.get("evidence", []), "decision": decision}
