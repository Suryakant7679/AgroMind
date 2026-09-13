"""Initialize the project MCP servers and verify their advertised tools."""
from __future__ import annotations
import asyncio
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SERVERS = {
    "context7": (["node_modules/@upstash/context7-mcp/dist/index.js"], {"resolve-library-id", "query-docs"}),
    "playwright": (["node_modules/@playwright/mcp/cli.js", "--headless", "--isolated"], {"browser_navigate", "browser_snapshot"}),
}

async def check(name: str, args: list[str], expected: set[str]) -> None:
    async with asyncio.timeout(45):
        parameters = StdioServerParameters(command="node", args=args, cwd=str(ROOT))
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                names = {tool.name for tool in result.tools}
                if not expected <= names:
                    raise RuntimeError(f"{name}: missing tools {expected - names}")
                print(f"{name}: initialized; {len(names)} tools; required tools verified", flush=True)

async def main() -> None:
    for name, (args, expected) in SERVERS.items():
        await check(name, args, expected)

if __name__ == "__main__":
    asyncio.run(main())
