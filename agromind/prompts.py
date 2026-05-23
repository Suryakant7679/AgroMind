from agromind.data import MEDICAL_DISCLAIMER, get_domain, get_tool


def build_system_prompt(domain_id: str, tool_id: str, language_name: str = "English") -> str:
    domain = get_domain(domain_id)
    tool = get_tool(domain_id, tool_id)
    safety = ""
    if domain_id == "healthcare":
        safety = (
            f'Always include this exact disclaimer near the top: "{MEDICAL_DISCLAIMER}" '
            "Flag emergency symptoms clearly and recommend urgent professional care when relevant."
        )

    agri_instructions = ""
    if tool_id == "agriculture-tools":
        agri_instructions = (
            "You are operating as the central agronomic engine of the AgroMind Precision Agriculture Dashboard.\n"
            "Analyze any provided 'live_environmental_telemetry' (soil grids data, Open-Meteo 7-day forecast, and NASA solar index) to customize the dosages and water volumes.\n"
            "CRITICAL: In addition to a beautifully structured, highly practical agricultural markdown report, you MUST append a valid, parseable JSON block at the very bottom of your response enclosed in ```json and ``` tags. This JSON block drives the real-time SaaS widgets on the farmer's dashboard. Fill all fields with realistic, intelligent agronomic estimations based on the inputs and telemetry:\n"
            "```json\n"
            "{\n"
            "  \"npk\": {\"n\": 45, \"p\": 30, \"k\": 20},\n"
            "  \"water_req_liters_per_acre\": 15000,\n"
            "  \"drought_flood_risk\": \"low\",\n"
            "  \"estimated_harvest_days\": 120,\n"
            "  \"mandi_live_price\": \"INR 3,250 / quintal\",\n"
            "  \"mandi_predicted_price\": \"INR 3,500 / quintal\",\n"
            "  \"weather_alerts\": [\"frost alert\", \"storm warning\"],\n"
            "  \"disease_risk\": \"low\",\n"
            "  \"ndvi_health_index\": 0.85\n"
            "}\n"
            "```\n"
            "Do not omit any keys in the JSON block, and keep it valid JSON."
        )

    parts = [
        "You are AgroMind AI, a careful multi-domain assistant.",
        f"Respond only in {language_name}. Keep technical terms clear and explain them simply when needed.",
        "Return concise, structured Markdown with headings, bullet points, tables when useful, and a short next-steps checklist.",
        "Do not fabricate lab values, market prices, weather, government rules, or diagnoses. State uncertainty and what extra data is needed.",
        "For uploaded images or PDFs, explain that analysis depends on file readability and the configured multimodal provider.",
        f"Domain: {domain['name']}. {domain['description']}" if domain else "",
        f"Tool: {tool['title']}. Required output areas: {', '.join(tool['output_hints'])}." if tool else "",
        agri_instructions,
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
