from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.python_tools import python_package_info, run_restricted_python


mcp = FastMCP("AIOS Python", instructions="Restricted, isolated Python calculations with no imports or file access.")


@mcp.tool()
def run_python(code: str, timeout_seconds: int = 5) -> dict:
    """Run restricted Python; assign a JSON-compatible value to `result` to return it."""
    return run_restricted_python(code, timeout_seconds)


@mcp.tool()
def package_info(package: str) -> dict:
    """Inspect installed Python distribution metadata without importing the package."""
    return python_package_info(package)

if __name__ == "__main__":
    mcp.run(transport="stdio")
