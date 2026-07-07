import asyncio
import html
import json
import math
import re
import sys
from typing import Any


SERVER_NAME = "agromind-education-render"
SERVER_VERSION = "0.1.0"


TOOLS = [
    {
        "name": "render_plot_svg",
        "description": "Render a lightweight SVG plot for classroom math/science explanations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "expression": {"type": "string", "description": "Example: y=x^2, y=2*x+1, sin(x)"},
                "plot_type": {"type": "string", "description": "function or line"},
                "x_min": {"type": "number"},
                "x_max": {"type": "number"},
            },
            "required": ["title"],
        },
    },
]


def text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _safe_eval_expression(expression: str, x: float) -> float:
    expr = expression.strip().lower()
    if "=" in expr:
        expr = expr.split("=", 1)[1]
    expr = expr.replace("^", "**")
    expr = re.sub(r"\b(\d+)x\b", r"\1*x", expr)
    allowed_names = {
        "x": x,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "sqrt": math.sqrt,
        "log": math.log,
        "abs": abs,
        "pi": math.pi,
        "e": math.e,
    }
    value = eval(expr, {"__builtins__": {}}, allowed_names)
    return float(value)


def _default_expression(title: str, expression: str) -> str:
    candidate = expression.strip()
    if candidate:
        return candidate
    match = re.search(r"y\s*=\s*([a-z0-9+\-*/^().\s]+)", title, flags=re.IGNORECASE)
    if match:
        return "y=" + match.group(1).strip()
    return "y=x"


def render_plot_svg(title: str, expression: str = "", plot_type: str = "function", x_min: float = -5, x_max: float = 5) -> str:
    chart_title = title.strip() or "AgroMind plot"
    expr = _default_expression(chart_title, expression)
    left, top, width, height = 48, 32, 400, 260
    plot_left, plot_top, plot_width, plot_height = 56, 56, 328, 156
    x_start = float(x_min if x_min is not None else -5)
    x_end = float(x_max if x_max is not None else 5)
    if x_start >= x_end:
        x_start, x_end = -5, 5

    points: list[tuple[float, float]] = []
    for idx in range(81):
        x = x_start + (x_end - x_start) * idx / 80
        try:
            y = _safe_eval_expression(expr, x)
        except Exception:
            y = x
        if math.isfinite(y):
            points.append((x, y))

    y_values = [y for _, y in points] or [0]
    y_min = min(y_values)
    y_max = max(y_values)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    y_padding = max((y_max - y_min) * 0.12, 1)
    y_min -= y_padding
    y_max += y_padding

    def sx(x: float) -> float:
        return plot_left + ((x - x_start) / (x_end - x_start)) * plot_width

    def sy(y: float) -> float:
        return plot_top + plot_height - ((y - y_min) / (y_max - y_min)) * plot_height

    polyline = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in points)
    zero_x = sx(0) if x_start <= 0 <= x_end else plot_left
    zero_y = sy(0) if y_min <= 0 <= y_max else plot_top + plot_height
    escaped_title = html.escape(chart_title)
    escaped_expr = html.escape(expr)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escaped_title}">
  <rect width="{width}" height="{height}" rx="8" fill="#ffffff"/>
  <rect x="{plot_left}" y="{plot_top}" width="{plot_width}" height="{plot_height}" fill="#f8fafc" stroke="#d7dee8"/>
  <line x1="{plot_left}" y1="{zero_y:.1f}" x2="{plot_left + plot_width}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-width="1"/>
  <line x1="{zero_x:.1f}" y1="{plot_top}" x2="{zero_x:.1f}" y2="{plot_top + plot_height}" stroke="#94a3b8" stroke-width="1"/>
  <polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="{left}" y="28" fill="#0f172a" font-family="Arial, sans-serif" font-size="16" font-weight="700">{escaped_title}</text>
  <text x="{left}" y="238" fill="#475569" font-family="Arial, sans-serif" font-size="12">Expression: {escaped_expr}</text>
  <text x="{plot_left}" y="226" fill="#64748b" font-family="Arial, sans-serif" font-size="11">x: {x_start:g} to {x_end:g}</text>
  <text x="302" y="226" fill="#64748b" font-family="Arial, sans-serif" font-size="11">y: {y_min:g} to {y_max:g}</text>
</svg>"""


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "render_plot_svg":
        return text_result(
            render_plot_svg(
                str(arguments.get("title", "")),
                str(arguments.get("expression", "")),
                str(arguments.get("plot_type", "function")),
                float(arguments.get("x_min", -5)),
                float(arguments.get("x_max", 5)),
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
