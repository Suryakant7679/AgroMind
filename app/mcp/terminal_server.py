from mcp.server.fastmcp import FastMCP
from app.mcp.terminal_tools import run_terminal

mcp = FastMCP("AIOS Terminal", instructions="Shell-free execution of explicitly allowlisted commands.")

@mcp.tool()
def run_command(command: str, args: list[str] | None = None, timeout: int = 15) -> dict:
    """Run one allowlisted executable without invoking a shell."""
    return run_terminal(command, args, timeout)

if __name__ == "__main__": mcp.run(transport="stdio")
