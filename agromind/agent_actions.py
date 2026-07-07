from __future__ import annotations

import re
from datetime import UTC, datetime

from agromind.data import get_domain, get_tool
from agromind.integrations import gmail, google_sheets, x
from agromind.supabase_store import (
    create_agent_action_draft,
    fetch_agent_action_draft,
    fetch_output_by_id,
    save_agent_action_run,
    update_agent_action_draft,
)


ACTION_CONFIG = {
    "save_sheet": {"provider": "google_sheets", "label": "Save to Google Sheet"},
    "send_gmail": {"provider": "gmail", "label": "Send by Gmail"},
    "post_x": {"provider": "x", "label": "Post to X"},
}


def _plain_text(markdown_text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", markdown_text or "")
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_#>`~-]+", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tool_title(output: dict) -> str:
    domain = get_domain(output.get("domain"))
    tool = get_tool(output.get("domain"), output.get("tool"))
    domain_name = domain["name"] if domain else output.get("domain", "AgroMind")
    tool_name = tool["title"] if tool else output.get("tool", "AI Output")
    return f"{domain_name} - {tool_name}"


def build_action_payload(action_type: str, output: dict, user_email: str = "") -> dict:
    text = _plain_text(output.get("output_markdown", ""))
    title = _tool_title(output)
    prompt = output.get("prompt") or {}
    created_at = output.get("created_at") or datetime.now(UTC).isoformat()

    if action_type == "save_sheet":
        return {
            "sheet_name": "AgroMind Records",
            "columns": ["created_at", "user_email", "domain", "tool", "prompt", "output"],
            "row": {
                "created_at": created_at,
                "user_email": user_email,
                "domain": output.get("domain"),
                "tool": output.get("tool"),
                "prompt": prompt,
                "output": output.get("output_markdown", ""),
            },
            "summary": f"Append this {title} result to the external sheet.",
        }

    if action_type == "send_gmail":
        return {
            "to": "",
            "subject": f"AgroMind Result: {title}",
            "body": text,
            "summary": "Review recipient, subject, and body before sending.",
        }

    if action_type == "post_x":
        compact = re.sub(r"\s+", " ", text).strip()
        post_text = compact[:270].rstrip()
        if len(compact) > len(post_text):
            post_text = post_text.rstrip(". ") + "..."
        return {
            "text": post_text,
            "summary": "Review this short social post before publishing.",
        }

    raise ValueError("Unknown action type.")


def create_draft_for_output(
    user_id: str,
    user_email: str,
    output_id: str,
    action_type: str,
    access_token: str | None = None,
) -> dict:
    if action_type not in ACTION_CONFIG:
        raise ValueError("Unsupported agent action.")

    output = fetch_output_by_id(output_id, access_token)
    if not output:
        raise ValueError("Output not found.")
    if output.get("user_id") and str(output.get("user_id")) != str(user_id):
        raise PermissionError("This output belongs to another user.")

    config = ACTION_CONFIG[action_type]
    payload = build_action_payload(action_type, output, user_email)
    draft = create_agent_action_draft(
        user_id=user_id,
        source_output_id=output_id,
        action_type=action_type,
        provider=config["provider"],
        draft_payload=payload,
        access_token=access_token,
    )
    if not draft:
        raise RuntimeError("Could not save action draft. Check Supabase schema and credentials.")
    return draft


def execute_approved_draft(user_id: str, draft_id: str, access_token: str | None = None) -> dict:
    draft = fetch_agent_action_draft(draft_id, access_token)
    if not draft:
        raise ValueError("Action draft not found.")
    if draft.get("user_id") and str(draft.get("user_id")) != str(user_id):
        raise PermissionError("This action draft belongs to another user.")
    if draft.get("status") not in {"pending", "approved", "failed"}:
        raise ValueError(f"Draft cannot be executed from status {draft.get('status')}.")

    payload = draft.get("draft_payload") or {}
    provider = draft.get("provider")
    update_agent_action_draft(draft_id, {"status": "approved"}, access_token)

    try:
        if provider == "google_sheets":
            result = google_sheets.append_row(payload)
        elif provider == "gmail":
            result = gmail.send_draft(payload)
        elif provider == "x":
            result = x.publish_post(payload)
        else:
            raise RuntimeError(f"No connector is registered for provider {provider}.")
    except Exception as exc:
        message = str(exc)
        update_agent_action_draft(draft_id, {"status": "failed"}, access_token)
        save_agent_action_run(draft_id, user_id, provider, "failed", error=message, access_token=access_token)
        raise RuntimeError(message) from exc

    update_agent_action_draft(draft_id, {"status": "executed"}, access_token)
    save_agent_action_run(draft_id, user_id, provider, "executed", result=result, access_token=access_token)
    return result
