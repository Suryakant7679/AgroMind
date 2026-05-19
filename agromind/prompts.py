from agromind.data import MEDICAL_DISCLAIMER, get_domain, get_tool


def build_system_prompt(domain_id: str, tool_id: str) -> str:
    domain = get_domain(domain_id)
    tool = get_tool(domain_id, tool_id)
    safety = ""
    if domain_id == "healthcare":
        safety = (
            f'Always include this exact disclaimer near the top: "{MEDICAL_DISCLAIMER}" '
            "Flag emergency symptoms clearly and recommend urgent professional care when relevant."
        )

    parts = [
        "You are AgroMind AI, a careful multi-domain assistant.",
        "Return concise, structured Markdown with headings, bullet points, tables when useful, and a short next-steps checklist.",
        "Do not fabricate lab values, market prices, weather, government rules, or diagnoses. State uncertainty and what extra data is needed.",
        "For uploaded images or PDFs, explain that analysis depends on file readability and the configured multimodal provider.",
        f"Domain: {domain['name']}. {domain['description']}" if domain else "",
        f"Tool: {tool['title']}. Required output areas: {', '.join(tool['output_hints'])}." if tool else "",
        safety,
    ]
    return "\n".join(part for part in parts if part)


def build_user_prompt(fields: dict[str, str], file_summary: str | None = None) -> str:
    details = "\n".join(f"- {key}: {value}" for key, value in fields.items() if value.strip())
    sections = [f"User inputs:\n{details or '- No text fields provided.'}"]
    if file_summary:
        sections.append(f"Uploaded asset:\n{file_summary}")
    return "\n\n".join(sections)


def fallback_response(domain_id: str, tool_id: str, fields: dict[str, str]) -> str:
    tool = get_tool(domain_id, tool_id)
    title = tool["title"] if tool else "AI Tool"
    rows = "\n".join(f"| {key} | {value} |" for key, value in fields.items() if value)
    disclaimer = f"> {MEDICAL_DISCLAIMER}\n" if domain_id == "healthcare" else ""
    hints = ", ".join(tool["output_hints"]) if tool else "the selected tool"
    return f"""## {title} Report

The provider keys are not configured yet, so this response shows the expected report format.

{disclaimer}
### Input Summary
| Field | Value |
| --- | --- |
{rows or "| Request | No details provided |"}

### Report Structure
- The submitted fields were received and validated.
- Add `OPENAI_API_KEY` or `GEMINI_API_KEY` to enable provider-backed responses.
- The final response will follow the required structure for {hints}.

### Next Steps
1. Configure Supabase and AI provider keys.
2. Run the tool again with realistic inputs and an uploaded file when needed.
3. Export the report or generate a PPT from the dashboard.
"""
