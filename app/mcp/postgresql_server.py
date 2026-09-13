from mcp.server.fastmcp import FastMCP
from app.config import load_env
from app.mcp.postgresql_tools import PostgreSQLReader
load_env(); mcp = FastMCP("AIOS PostgreSQL", instructions="Read-only PostgreSQL schema and query tools."); db = PostgreSQLReader()
@mcp.tool()
def postgres_tables() -> list[dict]: return db.tables()
@mcp.tool()
def postgres_columns(table: str, schema: str = "public") -> list[dict]: return db.columns(table, schema)
@mcp.tool()
def postgres_query(sql: str, parameters: list | None = None, limit: int = 200) -> dict: return db.query(sql, parameters, limit)
if __name__ == "__main__": mcp.run(transport="stdio")
