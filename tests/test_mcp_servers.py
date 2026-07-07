import asyncio

from agromind.mcp_servers.agriculture import call_tool, handle_request
from agromind.mcp_servers.education import call_tool as call_education_tool
from agromind.mcp_servers.education import handle_request as handle_education_request
from agromind.mcp_servers.health import call_tool as call_health_tool
from agromind.mcp_servers.health import handle_request as handle_health_request


def test_agriculture_mcp_lists_tools():
    response = asyncio.run(handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))

    assert response["result"]["tools"]
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "get_crop_calendar" in names
    assert "get_environmental_context" in names
    assert "get_mandi_price_guidance" in names


def test_agriculture_mcp_crop_calendar_tool():
    response = asyncio.run(
        call_tool(
            "get_crop_calendar",
            {"crop": "tomato", "season": "kharif", "state": "maharashtra"},
        )
    )

    text = response["content"][0]["text"]
    assert "Tomato calendar" in text
    assert "Maharashtra" in text


def test_health_mcp_lists_tools():
    response = asyncio.run(handle_health_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))

    assert response["result"]["tools"]
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "lookup_lab_marker" in names
    assert "lookup_drug_safety" in names
    assert "get_symptom_red_flags" in names
    assert "search_health_evidence_guidance" in names


def test_health_mcp_lab_marker_tool():
    response = asyncio.run(
        call_health_tool(
            "lookup_lab_marker",
            {"marker": "HbA1c", "value": "7.2%"},
        )
    )

    text = response["content"][0]["text"]
    assert "HbA1c" in text
    assert "average blood sugar" in text
    assert "educational" in text


def test_health_mcp_drug_safety_tool_does_not_prescribe():
    response = asyncio.run(
        call_health_tool(
            "lookup_drug_safety",
            {"drug_name": "ibuprofen", "context": "kidney disease"},
        )
    )

    text = response["content"][0]["text"]
    assert "Medication safety check" in text
    assert "kidney disease" in text
    assert "Do not start, stop, or change dose" in text


def test_education_mcp_lists_tools():
    response = asyncio.run(handle_education_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))

    assert response["result"]["tools"]
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "get_youtube_learning_context" in names
    assert "create_quiz_plan" in names
    assert "create_revision_plan" in names
    assert "create_lesson_outline" in names


def test_education_mcp_quiz_plan_tool():
    response = asyncio.run(
        call_education_tool(
            "create_quiz_plan",
            {"topic": "photosynthesis", "level": "class 8", "count": 12},
        )
    )

    text = response["content"][0]["text"]
    assert "photosynthesis" in text
    assert "Total questions: 12" in text
    assert "answer key" in text


def test_education_mcp_rejects_invalid_youtube_url_without_network():
    response = asyncio.run(
        call_education_tool(
            "get_youtube_learning_context",
            {"url": "not a youtube url"},
        )
    )

    text = response["content"][0]["text"]
    assert "Invalid YouTube URL" in text
