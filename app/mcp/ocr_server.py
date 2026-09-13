from mcp.server.fastmcp import FastMCP

from app.mcp.ocr_tools import OCRReader

mcp = FastMCP("AIOS OCR", instructions="Workspace-confined OCR for images and configured scanned-PDF engines.")
ocr = OCRReader()


@mcp.tool()
def extract_text(path: str, language: str = "eng", timeout: int = 30) -> dict:
    return ocr.extract(path, language, timeout)


if __name__ == "__main__": mcp.run(transport="stdio")
