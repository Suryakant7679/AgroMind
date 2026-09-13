from mcp.server.fastmcp import FastMCP
from app.config import load_env
from app.mcp.sqlite_tools import SQLiteReader
load_env(); mcp = FastMCP("AIOS SQLite", instructions="Workspace-confined read-only SQLite tools."); db = SQLiteReader()
@mcp.tool()
def sqlite_tables() -> list[dict]: return db.tables()
@mcp.tool()
def sqlite_query(sql: str, parameters: list | None = None, limit: int = 200) -> dict: return db.query(sql, parameters, limit)
if __name__ == "__main__": mcp.run(transport="stdio")
