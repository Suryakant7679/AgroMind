import asyncio
import json
import sys
from typing import Any


SERVER_NAME = "agromind-health-evidence"
SERVER_VERSION = "0.1.0"


TOOLS = [
    {
        "name": "lookup_lab_marker",
        "description": "Explain a common lab marker in plain language with follow-up guidance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "marker": {"type": "string", "description": "Example: hemoglobin, hba1c, tsh, creatinine"},
                "value": {"type": "string", "description": "Optional reported value with units"},
            },
            "required": ["marker"],
        },
    },
    {
        "name": "lookup_drug_safety",
        "description": "Return high-level medication safety questions and precautions. This does not prescribe.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drug_name": {"type": "string"},
                "context": {"type": "string", "description": "Age, pregnancy, allergies, conditions, current medicines"},
            },
            "required": ["drug_name"],
        },
    },
    {
        "name": "get_symptom_red_flags",
        "description": "Return urgent-care red flags for a symptom or health concern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symptom": {"type": "string"},
                "age": {"type": "string"},
            },
            "required": ["symptom"],
        },
    },
    {
        "name": "search_health_evidence_guidance",
        "description": "Return safe search strategy and trusted evidence sources for a health topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
            },
            "required": ["topic"],
        },
    },
]


LAB_MARKERS = {
    "hemoglobin": (
        "Hemoglobin carries oxygen in red blood cells. Low values can suggest anemia, bleeding, nutritional deficiency, "
        "chronic disease, or other causes. High values can relate to dehydration, smoking, lung/heart conditions, or altitude."
    ),
    "hba1c": (
        "HbA1c estimates average blood sugar over roughly 2-3 months. It is used for diabetes screening and monitoring, "
        "but interpretation depends on the lab range, anemia status, pregnancy, kidney disease, and clinician context."
    ),
    "tsh": (
        "TSH is a pituitary signal used to evaluate thyroid function. High TSH often points toward underactive thyroid, "
        "while low TSH can suggest overactive thyroid or medication effects. Free T4/T3 and symptoms matter."
    ),
    "creatinine": (
        "Creatinine is used to estimate kidney filtration. Interpretation depends on age, sex, muscle mass, hydration, "
        "medicines, and eGFR. Sudden rises need prompt clinician review."
    ),
    "alt": (
        "ALT is a liver enzyme. Higher values can occur with fatty liver, viral hepatitis, alcohol, medicines, muscle injury, "
        "or other liver stress. Pattern with AST, bilirubin, ALP, and symptoms matters."
    ),
}


DRUG_SAFETY_PROMPTS = {
    "paracetamol": "Check total daily dose, liver disease, alcohol use, duplicate cold/flu medicines, and child weight-based dosing.",
    "acetaminophen": "Check total daily dose, liver disease, alcohol use, duplicate cold/flu medicines, and child weight-based dosing.",
    "ibuprofen": "Ask about stomach ulcers, kidney disease, blood thinners, heart disease, high blood pressure, asthma sensitivity, and pregnancy.",
    "aspirin": "Ask about bleeding risk, ulcers, blood thinners, children/teens with viral illness, allergy, pregnancy, and planned surgery.",
    "amoxicillin": "Ask about penicillin allergy, prior severe rash, kidney disease, pregnancy, and whether an antibiotic was prescribed by a clinician.",
    "metformin": "Ask about kidney function/eGFR, dehydration, severe infection, contrast scans, heavy alcohol use, and gastrointestinal side effects.",
}


GENERAL_RED_FLAGS = [
    "Chest pain, severe shortness of breath, fainting, blue lips, or severe weakness.",
    "Stroke signs: face drooping, arm weakness, speech trouble, sudden severe headache, or confusion.",
    "Severe allergic reaction: swelling of face/lips/tongue, wheezing, widespread hives, or collapse.",
    "Severe dehydration, persistent vomiting, stiff neck with fever, seizure, or loss of consciousness.",
    "Heavy bleeding, black stools, severe abdominal pain, or severe injury.",
    "Suicidal thoughts, self-harm risk, or danger to others.",
]


def text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def normalize(value: str) -> str:
    return value.strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def lab_marker(marker: str, value: str = "") -> str:
    key = normalize(marker)
    matched = next((name for name in LAB_MARKERS if normalize(name) == key), "")
    explanation = LAB_MARKERS.get(matched) or (
        "This marker is not in AgroMind's starter reference set yet. Use the lab's reference range and clinical context."
    )
    value_line = f"\nReported value: {value.strip()}" if value.strip() else ""
    return (
        f"Lab marker: {marker.strip() or 'Unknown'}{value_line}\n\n"
        f"{explanation}\n\n"
        "Safety note: This explanation is educational. Interpretation should use the lab reference range, symptoms, "
        "medical history, medicines, and clinician review."
    )


def drug_safety(drug_name: str, context: str = "") -> str:
    drug = drug_name.strip()
    key = normalize(drug)
    matched = next((name for name in DRUG_SAFETY_PROMPTS if normalize(name) == key), "")
    precautions = DRUG_SAFETY_PROMPTS.get(matched) or (
        "Ask about age, pregnancy, allergies, kidney/liver disease, other medicines, dose, duration, and why it is being used."
    )
    context_line = f"\nUser context: {context.strip()}" if context.strip() else ""
    return (
        f"Medication safety check: {drug or 'Unknown medicine'}{context_line}\n\n"
        f"- Key checks: {precautions}\n"
        "- Do not start, stop, or change dose without a qualified clinician or pharmacist when risk factors are present.\n"
        "- Seek urgent care for breathing difficulty, swelling, severe rash, fainting, overdose, severe bleeding, or confusion."
    )


def red_flags(symptom: str, age: str = "") -> str:
    age_line = f"Age/context: {age.strip()}\n" if age.strip() else ""
    bullets = "\n".join(f"- {item}" for item in GENERAL_RED_FLAGS)
    return (
        f"Urgent-care red flags for: {symptom.strip() or 'health concern'}\n"
        f"{age_line}\n"
        f"{bullets}\n\n"
        "If any red flag is present, seek emergency or urgent medical care. This is education and triage support only."
    )


def evidence_guidance(topic: str) -> str:
    topic_text = topic.strip() or "health topic"
    return (
        f"Evidence lookup guidance for: {topic_text}\n\n"
        "- Prefer sources such as WHO, CDC, NIH/MedlinePlus, NICE, FDA labels, PubMed abstracts, and national guidelines.\n"
        "- Check publication date, population studied, strength of evidence, conflicts of interest, and whether guidance applies locally.\n"
        "- Avoid treating blogs, ads, anecdotes, and social posts as clinical evidence.\n"
        "- For patient-specific decisions, use this evidence only as preparation for a clinician/pharmacist discussion."
    )


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "lookup_lab_marker":
        return text_result(lab_marker(str(arguments.get("marker", "")), str(arguments.get("value", ""))))

    if name == "lookup_drug_safety":
        return text_result(drug_safety(str(arguments.get("drug_name", "")), str(arguments.get("context", ""))))

    if name == "get_symptom_red_flags":
        return text_result(red_flags(str(arguments.get("symptom", "")), str(arguments.get("age", ""))))

    if name == "search_health_evidence_guidance":
        return text_result(evidence_guidance(str(arguments.get("topic", ""))))

    raise ValueError(f"Unknown tool: {name}")


async def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        result = await call_tool(str(params.get("name", "")), params.get("arguments") or {})
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = await handle_request(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32000, "message": str(exc)},
            }
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
