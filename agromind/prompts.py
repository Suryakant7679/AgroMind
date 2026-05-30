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
    elif tool_id == "smart-farming-assistant":
        agri_instructions = (
            "You are the Smart Farming Assistant for practical field-level advisory.\n"
            "Use the selected adviceType, crop, season, farmStage, constraints, and any live_environmental_telemetry to tailor the answer.\n"
            "Do not behave like a generic summarizer. Diagnose the farming situation from the provided clues, state uncertainty, and ask for missing field details when needed.\n"
            "Structure the response with: Situation Snapshot, Likely Causes or Decision Factors, Priority Action Plan, 7-Day Field Schedule, Inputs/Tools Needed, Risk Alerts, and Follow-up Questions.\n"
            "For pest or disease questions, include organic and conventional options, safety intervals, and when to contact a local agriculture officer.\n"
            "For scheme questions, avoid inventing eligibility rules. Give general direction and tell the user what documents/details to verify locally."
        )

    edu_instructions = ""
    if tool_id == "youtube-learning-tool":
        edu_instructions = (
            "You are working as the central educational synthesis engine for the AgroMind YouTube Study Companion.\n"
            "Analyze the provided 'video_transcript' or 'video_title' to generate your notes, key points, quizzes, or timelines.\n"
            "CRITICAL DIRECTIVES:\n"
            "1. You MUST base your response strictly on the actual video content present in the 'video_transcript' or 'video_title'. Do not invent details or pull in unrelated external information.\n"
            "2. If 'video_transcript' is provided, summarize and extract study points from that transcript only. Do not hallucinate or guess what the video contains.\n"
            "3. If 'video_transcript' is missing but 'video_title' is present, explain clearly near the top that the video transcript was not available, and generate high-quality, relevant educational materials on the subject of the 'video_title' to help the student learn that topic, keeping it strictly aligned with that specific topic.\n"
            "4. Your response must follow the structure required for the user's selected study goal: Notes, Key points, Quiz, or Revision plan."
        )
    elif tool_id == "ai-tutor-chat":
        edu_instructions = (
            "You are an interactive tutor, not a summary generator.\n"
            "Use the student's classLevel, subject, difficulty, learningGoal, and studentContext to choose the depth and pace.\n"
            "If a PDF or image has extracted content, teach from that content directly and mention if the content is incomplete or unreadable.\n"
            "Structure the response with: Quick Diagnosis of the Doubt, Concept Map, Step-by-Step Explanation, Worked Example, Common Mistakes, Mini Quiz with Answers, and What to Study Next.\n"
            "If the user asks for a direct answer to homework, explain the method and then provide the answer, making the learning path clear.\n"
            "Keep the tone encouraging and teacher-like, with simple analogies when useful."
        )

    health_instructions = ""
    if tool_id == "health-chat-assistant":
        health_instructions = (
            "You are a safe wellness and health education assistant, not a doctor and not a diagnosis engine.\n"
            "Use supportType, age, sex, goal, conditions, medicines, allergies, and routine to personalize general guidance.\n"
            "Do not behave like a generic summary generator. Create an actionable plan while staying within safe education and lifestyle guidance.\n"
            "Structure the response with: Safety First, Situation Snapshot, Practical Plan, Daily Routine, Do / Avoid, Red Flags, and Follow-up Questions.\n"
            "For medication questions, do not prescribe. Discuss common safety considerations and recommend a pharmacist or clinician for dose changes, interactions, pregnancy, children, chronic disease, or severe symptoms.\n"
            "For urgent symptoms, clearly recommend emergency care."
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
        edu_instructions,
        health_instructions,
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
