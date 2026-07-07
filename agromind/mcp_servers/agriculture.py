import asyncio
import json
import sys
from typing import Any

from agromind.ai import fetch_environmental_context


SERVER_NAME = "agromind-agriculture"
SERVER_VERSION = "0.1.0"


TOOLS = [
    {
        "name": "get_environmental_context",
        "description": "Fetch weather, soil, and location context for a farm location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Village, city, district, state, or latitude, longitude.",
                }
            },
            "required": ["location"],
        },
    },
    {
        "name": "get_crop_calendar",
        "description": "Return a practical Indian crop calendar summary for a crop and season.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "crop": {"type": "string"},
                "season": {"type": "string", "description": "Kharif, Rabi, Zaid, or Perennial"},
                "state": {"type": "string"},
            },
            "required": ["crop"],
        },
    },
    {
        "name": "get_mandi_price_guidance",
        "description": "Return safe market-price guidance and the inputs needed for a live mandi lookup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "crop": {"type": "string"},
                "state": {"type": "string"},
                "district": {"type": "string"},
            },
            "required": ["crop"],
        },
    },
]


def text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def crop_calendar(crop: str, season: str = "", state: str = "") -> str:
    crop_name = crop.strip().title() or "Selected crop"
    season_name = season.strip().title() or "local season"
    state_name = state.strip().title() or "your region"
    return (
        f"{crop_name} calendar for {state_name} ({season_name}):\n"
        "- Confirm local sowing window with the nearest agriculture extension office.\n"
        "- Before sowing: test soil pH/NPK, choose certified seed, and plan irrigation.\n"
        "- Early stage: monitor germination, weeds, and seedling pests every 3-5 days.\n"
        "- Vegetative stage: balance nitrogen with crop condition; avoid over-irrigation.\n"
        "- Flowering/fruiting: watch heat, water stress, and pest pressure closely.\n"
        "- Pre-harvest: check market price trend, moisture requirements, and storage plan.\n"
        "Ask for exact crop variety, sowing date, and district to make this calendar more precise."
    )


def mandi_guidance(crop: str, state: str = "", district: str = "") -> str:
    crop_name = crop.strip().title() or "Selected crop"
    place = ", ".join(part for part in [district.strip(), state.strip()] if part) or "your market"
    return (
        f"Market guidance for {crop_name} in {place}:\n"
        "- Live mandi pricing should be checked against a trusted local source before selling.\n"
        "- Compare nearby markets, transport cost, grade/quality, and expected arrival volume.\n"
        "- If prices are volatile, split sale quantity instead of selling the full harvest at once.\n"
        "- For a live lookup, provide crop/commodity, state, district, market name, and variety."
    )


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_environmental_context":
        location = str(arguments.get("location", "")).strip()
        if not location:
            return text_result("Location is required.")
        context = await fetch_environmental_context(location)
        return text_result(context or f"No environmental context could be resolved for {location}.")

    if name == "get_crop_calendar":
        return text_result(
            crop_calendar(
                str(arguments.get("crop", "")),
                str(arguments.get("season", "")),
                str(arguments.get("state", "")),
            )
        )

    if name == "get_mandi_price_guidance":
        return text_result(
            mandi_guidance(
                str(arguments.get("crop", "")),
                str(arguments.get("state", "")),
                str(arguments.get("district", "")),
            )
        )

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
