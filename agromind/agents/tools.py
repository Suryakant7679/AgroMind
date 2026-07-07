from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agromind.mcp_servers.agriculture import call_tool as call_agriculture_tool
from agromind.mcp_servers.education import call_tool as call_education_tool
from agromind.mcp_servers.health import call_tool as call_health_tool


@dataclass(frozen=True)
class AgentToolResult:
    server: str
    tool: str
    summary: str


KNOWN_CROPS = [
    "tomato",
    "wheat",
    "rice",
    "paddy",
    "onion",
    "cotton",
    "maize",
    "sugarcane",
    "potato",
    "chilli",
    "soybean",
]

KNOWN_STATES = [
    "maharashtra",
    "gujarat",
    "punjab",
    "haryana",
    "uttar pradesh",
    "madhya pradesh",
    "rajasthan",
    "karnataka",
    "tamil nadu",
    "telangana",
    "andhra pradesh",
    "bihar",
    "west bengal",
]

KNOWN_SEASONS = ["kharif", "rabi", "zaid", "perennial"]
LAB_MARKERS = ["hemoglobin", "hba1c", "tsh", "creatinine", "alt"]
DRUGS = ["paracetamol", "acetaminophen", "ibuprofen", "aspirin", "amoxicillin", "metformin"]


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _first_match(text: str, options: list[str], default: str = "") -> str:
    return next((option for option in options if option in text), default)


def _tool_text(result: dict[str, Any]) -> str:
    content = result.get("content") or []
    if not content:
        return ""
    return str(content[0].get("text", "")).strip()


async def _run(
    server: str,
    caller: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    tool: str,
    arguments: dict[str, Any],
) -> AgentToolResult:
    result = await caller(tool, arguments)
    return AgentToolResult(server=server, tool=tool, summary=_tool_text(result))


async def maybe_run_agent_tools(agent_id: str, message: str) -> list[AgentToolResult]:
    text = message.lower()
    if agent_id == "farmer":
        return await _farmer_tools(text, message)
    if agent_id == "doctor":
        return await _doctor_tools(text, message)
    if agent_id == "tutor":
        return await _tutor_tools(text, message)
    return []


async def _farmer_tools(text: str, message: str) -> list[AgentToolResult]:
    crop = _first_match(text, KNOWN_CROPS, "selected crop")
    state = _first_match(text, KNOWN_STATES)
    season = _first_match(text, KNOWN_SEASONS)

    if _has_any(text, ["mandi", "market", "price", "sell", "rate"]):
        return [
            await _run(
                "agromind-agriculture",
                call_agriculture_tool,
                "get_mandi_price_guidance",
                {"crop": crop, "state": state},
            )
        ]

    if _has_any(text, ["calendar", "sowing", "harvest", "season", "crop plan", "when to plant"]):
        return [
            await _run(
                "agromind-agriculture",
                call_agriculture_tool,
                "get_crop_calendar",
                {"crop": crop, "season": season, "state": state},
            )
        ]

    if crop != "selected crop":
        return [
            await _run(
                "agromind-agriculture",
                call_agriculture_tool,
                "get_crop_calendar",
                {"crop": crop, "season": season, "state": state},
            )
        ]

    return []


async def _doctor_tools(text: str, message: str) -> list[AgentToolResult]:
    marker = _first_match(text, LAB_MARKERS)
    if marker:
        return [
            await _run(
                "agromind-health-evidence",
                call_health_tool,
                "lookup_lab_marker",
                {"marker": marker},
            )
        ]

    drug = _first_match(text, DRUGS)
    if drug or _has_any(text, ["medicine", "drug", "tablet", "dose"]):
        return [
            await _run(
                "agromind-health-evidence",
                call_health_tool,
                "lookup_drug_safety",
                {"drug_name": drug or "mentioned medicine", "context": message},
            )
        ]

    if _has_any(text, ["fever", "pain", "rash", "symptom", "vomit", "bleeding", "breathing"]):
        return [
            await _run(
                "agromind-health-evidence",
                call_health_tool,
                "get_symptom_red_flags",
                {"symptom": message},
            )
        ]

    return []


async def _tutor_tools(text: str, message: str) -> list[AgentToolResult]:
    if _has_any(text, ["plot", "graph", "chart", "visualize", "visualise", "axis", "equation"]):
        return [
            await _run(
                "agromind-education",
                call_education_tool,
                "create_plot_plan",
                {"topic": message, "plot_type": "auto"},
            )
        ]

    if _has_any(text, ["quiz", "mcq", "test", "practice questions"]):
        return [
            await _run(
                "agromind-education",
                call_education_tool,
                "create_quiz_plan",
                {"topic": message, "count": 10},
            )
        ]

    if _has_any(text, ["revision", "revise", "study plan", "exam plan"]):
        return [
            await _run(
                "agromind-education",
                call_education_tool,
                "create_revision_plan",
                {"topic": message, "days": 7},
            )
        ]

    if _has_any(text, ["teach", "lesson", "explain", "class", "chapter"]):
        return [
            await _run(
                "agromind-education",
                call_education_tool,
                "create_lesson_outline",
                {"topic": message},
            )
        ]

    return []
