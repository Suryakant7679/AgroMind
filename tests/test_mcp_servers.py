import asyncio

from agromind.mcp_servers.agriculture import call_tool, handle_request


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
