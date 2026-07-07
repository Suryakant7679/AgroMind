import os

import httpx


def append_row(payload: dict) -> dict:
    """Append a row to an external sheet.

    For quick automation, set GOOGLE_SHEETS_WEBHOOK_URL to a Google Apps Script
    web app that accepts the payload. Full OAuth support can later replace this
    webhook without changing the approval workflow.
    """
    webhook_url = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("Google Sheets is not configured. Set GOOGLE_SHEETS_WEBHOOK_URL or add OAuth execution.")

    response = httpx.post(webhook_url, json=payload, timeout=20)
    response.raise_for_status()
    try:
        data = response.json()
    except Exception:
        data = {"text": response.text[:500]}
    return {"ok": True, "response": data}
