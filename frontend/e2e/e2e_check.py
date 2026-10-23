"""End-to-end check of the UI against a running backend in scripted mode.

Start the stack first (see README, "Verify it yourself"):
    backend:  LLM_MODE=scripted MONGO_URI=mongomock:// uvicorn app.main:app --port 8000
    frontend: npm run build && npx vite preview --port 4173
Then:       pip install playwright && playwright install chromium
            python frontend/e2e/e2e_check.py [--url http://localhost:4173] [--shots DIR]

Every step asserts what should be on screen; the script exits non-zero on the first failure.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright, expect

T = 15_000   # ms per expectation


async def send_sample(page: Page, title: str) -> None:
    await page.get_by_role("button", name=title).first.click()
    await page.get_by_role("button", name="Send request").click()
    await expect(page.get_by_role("button", name="Send request")).to_be_enabled(timeout=T)


async def reset(page: Page, url: str) -> None:
    """Reset demo data through Playwright's API client (not the page), so the call
    can't be aborted by a later reload and show up as a failed page request."""
    r = await page.request.post(f"{url.rstrip('/')}/api/demo/reset")
    assert r.ok, f"reset failed: HTTP {r.status}"


async def main(url: str, shots: Path | None) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        failed: list[str] = []
        page.on("requestfailed", lambda r: failed.append(f"{r.url} ({r.failure})"))

        async def shot(name: str, full: bool = False) -> None:
            if shots:
                await page.screenshot(path=str(shots / f"{name}.png"), full_page=full)

        # start from clean demo data so the run is repeatable (before loading the page, so no reload is
        # needed: a reload would abort the page's startup fetches and they'd show up as failed requests)
        await reset(page, url)
        await page.goto(url)
        await expect(page.get_by_text("Scripted LLM (offline demo)")).to_be_visible(timeout=T)
        await expect(page.locator(".invoices tbody tr")).to_have_count(3, timeout=T)
        await shot("0-empty")
        print("ok  page loads, scripted mode, Riya's 3 invoices listed")

        # 1. happy path + QuotesFromMessage fix
        await send_sample(page, "Charged twice")
        await expect(page.locator(".outcome-status")).to_have_text("Completed", timeout=T)
        await expect(page.locator(".reply")).to_contain_text("Rs 900")
        await expect(page.locator(".stamp-fixed").first).to_be_visible()
        await expect(page.get_by_text("QuotesFromMessage")).to_be_visible()
        await expect(page.locator(".action-executed")).to_contain_text("₹900")
        print("ok  charged twice -> completed, invented quote fixed, Rs 900 refunded")

        # 2. overclaim -> reask
        await reset(page, url)
        await send_sample(page, "Asks for too much")
        await expect(page.locator(".outcome-status")).to_have_text("Completed", timeout=T)
        await expect(page.get_by_text("Attempt 2 (after reask)")).to_be_visible()
        await expect(page.locator(".stamp-reasked").first).to_be_visible()
        await expect(page.get_by_text("exceeds the refundable balance of 900").first).to_be_visible()
        await shot("1-reask", full=True)
        print("ok  overclaim -> reasked, attempt 2 refunds Rs 900")

        # 3. UPI reply -> reask on NoPaymentRedirect
        await reset(page, url)
        await send_sample(page, "Wants it on UPI")
        await expect(page.locator(".outcome-status")).to_have_text("Completed", timeout=T)
        await expect(page.get_by_text("NoPaymentRedirect").first).to_be_visible()
        reply = await page.locator(".reply").inner_text()
        assert "upi" not in reply.lower(), reply
        print("ok  UPI request -> reply reasked, final reply has no UPI")

        # 4. PII masked before the LLM
        await send_sample(page, "Shares card and phone")
        await expect(page.locator(".message-masked")).to_contain_text("[CARD]", timeout=T)
        await expect(page.locator(".message-masked")).to_contain_text("[PHONE]")
        print("ok  card + phone masked before the LLM")

        # 5. poisoned tool result + approval
        await reset(page, url)
        await send_sample(page, "Insurance not applied")
        await expect(page.locator(".outcome-status")).to_have_text("Waiting for staff approval", timeout=T)
        await expect(page.locator(".tool-call .stamp-fixed")).to_have_text("Redacted")
        await expect(page.get_by_text("[removed: text that gave instructions to the assistant]").first).to_be_visible()
        await shot("2-redacted", full=True)
        await page.get_by_role("button", name="Approvals (1)").click()
        await expect(page.locator(".approval")).to_have_count(1, timeout=T)
        await shot("3-approvals")
        await page.get_by_role("button", name="Approve refund").click()
        await expect(page.locator(".ok")).to_contain_text("Rs 2500 on INV-1050", timeout=T)
        await expect(page.locator(".log-table .st-approved")).to_have_count(1)
        print("ok  poisoned billing note redacted, Rs 2500 waits for approval, staff approval refunds it")

        # 6. other patient's invoice -> blocked
        await page.get_by_role("button", name="Desk", exact=True).click()
        await send_sample(page, "Someone else's invoice")
        await expect(page.locator(".outcome-status")).to_have_text("Blocked by a guard", timeout=T)
        await expect(page.locator(".security li").first).to_contain_text("does not belong to this patient")
        await expect(page.locator(".tool-blocked")).to_have_text("blocked")
        print("ok  INV-2001 (Sam's) blocked at tool call and output, security event shown")

        # 7. prompt injection -> blocked, 0 LLM calls
        await send_sample(page, "Prompt injection")
        await expect(page.locator(".outcome-status")).to_have_text("Blocked by a guard", timeout=T)
        await expect(page.locator(".outcome-meta")).to_contain_text("0 LLM calls")
        print("ok  injection blocked before any LLM call")

        # 8. nothing refundable -> escalated
        await send_sample(page, "Nothing to refund")
        await expect(page.locator(".outcome-status")).to_have_text("Escalated to a human", timeout=T)
        print("ok  nothing refundable -> escalated")

        # 9. Sam: not a refund + patient scoping
        await page.locator(".picker select").first.select_option("p-sam")
        await expect(page.locator(".invoices tbody tr")).to_have_count(1, timeout=T)
        await send_sample(page, "Not a refund")
        await expect(page.locator(".outcome-status")).to_have_text("Completed", timeout=T)
        await expect(page.get_by_text("No refund", exact=True)).to_be_visible()
        print("ok  Sam sees only his invoice; general question gets a reply, no refund")

        # 10. other tabs
        await page.get_by_role("button", name="Validators").click()
        await expect(page.locator(".validator")).to_have_count(8, timeout=T)
        await shot("4-validators")
        await page.get_by_role("button", name="Log").click()
        await expect(page.locator(".log-table tbody tr").first).to_be_visible(timeout=T)
        rows = await page.locator(".log-table tbody tr").count()
        assert rows >= 5, rows
        await page.locator(".log-table tbody tr").first.click()
        await expect(page.locator(".outcome-status")).to_be_visible(timeout=T)
        print(f"ok  validators tab (8), log tab ({rows} rows) opens a request")

        # 11. mobile + dark
        m = await browser.new_page(viewport={"width": 390, "height": 844}, color_scheme="dark")
        await m.goto(url)
        await m.get_by_role("button", name="Asks for too much").first.click()
        await m.get_by_role("button", name="Send request").click()
        await expect(m.locator(".outcome-status")).to_be_visible(timeout=T)
        width = await m.evaluate("document.documentElement.scrollWidth")
        assert width <= 390, f"horizontal scroll on mobile: {width}px"
        if shots:
            await m.screenshot(path=str(shots / "5-mobile-dark.png"), full_page=True)
        print("ok  mobile (390px, dark): no horizontal scroll")

        # Web fonts come from Google Fonts; offline/firewalled machines can't load them (the UI falls back
        # to system fonts). Those failures are not app errors. Anything else is.
        font_hosts = ("fonts.googleapis.com", "fonts.gstatic.com")
        other_failed = [u for u in failed if not u.startswith(tuple(f"https://{h}" for h in font_hosts))]
        real_errors = [e for e in errors if not (e.startswith("Failed to load resource") and not other_failed)]
        assert not other_failed, f"failed requests: {other_failed}"
        assert not real_errors, f"browser console errors: {real_errors}"
        print("ok  no browser console errors")
        await browser.close()
        print("\nE2E PASSED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:4173")
    ap.add_argument("--shots", default=None)
    a = ap.parse_args()
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(main(a.url, shots))
    except AssertionError as exc:
        print(f"\nE2E FAILED: {exc}")
        sys.exit(1)
