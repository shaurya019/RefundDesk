"""Plain-Python detection logic, reused by the custom validators. Easy to unit test on its own."""
from __future__ import annotations

import re
import unicodedata

# ---------------- PII ----------------


def _luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# Order matters: cards before Aadhaar before phones, so a shorter pattern can't eat part of a longer one.
PII_PATTERNS: list[tuple[str, re.Pattern, object]] = [
    ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"), _luhn_ok),
    ("AADHAAR", re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)"), None),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), None),
    ("PHONE", re.compile(r"(?<![\w])(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)"), None),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("UPI_ID", re.compile(r"\b[\w.\-]{2,}@(?:ok\w+|ybl|ibl|axl|paytm|upi|apl)\b", re.IGNORECASE), None),
]


def mask_pii(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for kind, rx, check in PII_PATTERNS:
        def repl(m: re.Match, kind=kind, check=check) -> str:
            if check and not check(m.group(0)):
                return m.group(0)
            if kind not in found:
                found.append(kind)
            return f"[{kind}]"
        text = rx.sub(repl, text)
    return text, found


# ---------------- prompt injection ----------------

PATTERNS: list[tuple[str, str, int]] = [
    ("override", r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|all|your|system)\b"
                 r".{0,20}\b(instructions?|rules|prompts?|guidelines|policies)\b", 3),
    ("reveal_prompt", r"\b(reveal|show|print|repeat)\b.{0,30}\b(system prompt|instructions|policy)\b", 2),
    ("persona", r"\b(developer mode|jailbreak|do anything now|you are now)\b", 3),
    ("addressed_to_ai", r"\b(note|message|instructions?)\b.{0,15}\b(to|for)\b (the )?(ai|assistant|llm|bot|model)\b", 2),
    ("ai_must", r"\b(ai|assistant|llm|model|bot)\b.{0,30}\b(must|should|needs? to|is instructed to)\b", 1),
    ("fake_markup", r"(<\|?/?(system|im_start)\|?>|^\s*system\s*:)", 2),
    ("credential_ask", r"\b(upi pin|otp|cvv|password|net ?banking (login|password))\b", 2),
    ("approve_all", r"\b(approve|issue|process)\b.{0,30}\b(full|all|any|every)\b.{0,20}\brefunds?\b", 1),
]
_COMPILED = [(n, re.compile(p, re.IGNORECASE | re.MULTILINE), w) for n, p, w in PATTERNS]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub("[​-‏⁠-⁤﻿]", "", text)


def injection_score(text: str) -> tuple[int, list[str]]:
    t = normalize(text)
    hits = [(n, w) for n, rx, w in _COMPILED if rx.search(t)]
    return sum(w for _, w in hits), [n for n, _ in hits]


def redact_injected_lines(text: str, threshold: int) -> tuple[str, int]:
    """Replace each line that, on its own, scores >= threshold. Returns (text, lines_removed)."""
    out, removed = [], 0
    for line in text.splitlines():
        if injection_score(line)[0] >= threshold:
            out.append("[removed: text that gave instructions to the assistant]")
            removed += 1
        else:
            out.append(line)
    return "\n".join(out), removed


# ---------------- payment redirection in replies ----------------
PAYMENT_REDIRECT = re.compile(
    r"\b(upi|upi id|upi pin|gpay|phonepe|paytm|bank account number|ifsc|otp|cvv|advance payment|"
    r"pay (us|now)|send (the )?money|click (this|the) link)\b|https?://", re.IGNORECASE)

AMOUNT_IN_TEXT = re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.IGNORECASE)


def amounts_in(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in AMOUNT_IN_TEXT.findall(text)]
