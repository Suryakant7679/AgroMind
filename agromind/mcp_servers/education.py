import asyncio
import json
import sys
from typing import Any

from agromind.ai import extract_youtube_video_id, fetch_youtube_transcript_text, truncate_youtube_transcript


SERVER_NAME = "agromind-education"
SERVER_VERSION = "0.1.0"


TOOLS = [
    {
        "name": "get_youtube_learning_context",
        "description": "Extract a YouTube video id and transcript when available for study workflows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "create_quiz_plan",
        "description": "Create a quiz plan with question mix and answer-key guidance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "level": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "create_revision_plan",
        "description": "Create a practical revision plan for a topic or exam.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "days": {"type": "integer"},
                "level": {"type": "string"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "create_lesson_outline",
        "description": "Create a concise lesson outline for a teacher or tutor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "class_level": {"type": "string"},
                "duration_minutes": {"type": "integer"},
            },
            "required": ["topic"],
        },
    },
]


def text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


async def youtube_context(url: str) -> str:
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return "Invalid YouTube URL. Provide a standard YouTube watch, shorts, live, embed, or youtu.be link."

    transcript = fetch_youtube_transcript_text(video_id)
    if not transcript:
        return (
            f"Video id: {video_id}\n"
            "Transcript was not available from the server. Use the video title, user notes, or pasted transcript "
            "before making content-specific claims."
        )

    transcript, truncated = truncate_youtube_transcript(transcript)
    note = "\nTranscript note: truncated to the first available section." if truncated else ""
    return f"Video id: {video_id}\nTranscript:\n{transcript}{note}"


def quiz_plan(topic: str, level: str = "", count: int = 10) -> str:
    topic_text = topic.strip() or "Selected topic"
    level_text = level.strip() or "mixed level"
    question_count = max(1, min(int(count or 10), 50))
    mcq_count = max(1, question_count // 2)
    short_count = max(1, question_count // 4)
    application_count = max(0, question_count - mcq_count - short_count)
    return (
        f"Quiz plan for {topic_text} ({level_text}):\n"
        f"- Total questions: {question_count}\n"
        f"- MCQ: {mcq_count}\n"
        f"- Short answer: {short_count}\n"
        f"- Application/problem questions: {application_count}\n"
        "- Include an answer key, one-line explanations, and common mistakes.\n"
        "- Start easy, then increase difficulty so the learner can build confidence."
    )


def revision_plan(topic: str, days: int = 7, level: str = "") -> str:
    topic_text = topic.strip() or "Selected topic"
    day_count = max(1, min(int(days or 7), 60))
    level_text = level.strip() or "current learner level"
    return (
        f"{day_count}-day revision plan for {topic_text} ({level_text}):\n"
        "- Day 1: diagnose weak areas and collect notes/formulas/key terms.\n"
        "- Early days: revise core concepts with worked examples.\n"
        "- Middle days: solve mixed practice and explain mistakes.\n"
        "- Final days: timed quiz, flashcards, and rapid review.\n"
        "- Every day: 10-minute recall test without looking at notes."
    )


def lesson_outline(topic: str, class_level: str = "", duration_minutes: int = 45) -> str:
    topic_text = topic.strip() or "Selected topic"
    level_text = class_level.strip() or "target class"
    duration = max(10, min(int(duration_minutes or 45), 180))
    return (
        f"Lesson outline: {topic_text}\n"
        f"Class level: {level_text}\n"
        f"Duration: {duration} minutes\n\n"
        "1. Hook: quick question or real-world example.\n"
        "2. Objective: state what learners will be able to do.\n"
        "3. Explain: introduce the concept in small steps.\n"
        "4. Demonstrate: solve one example aloud.\n"
        "5. Practice: guided questions, then independent attempt.\n"
        "6. Check: short quiz or exit ticket.\n"
        "7. Homework: one easy, one medium, one challenge task."
    )


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_youtube_learning_context":
        return text_result(await youtube_context(str(arguments.get("url", ""))))

    if name == "create_quiz_plan":
        return text_result(
            quiz_plan(
                str(arguments.get("topic", "")),
                str(arguments.get("level", "")),
                int(arguments.get("count") or 10),
            )
        )

    if name == "create_revision_plan":
        return text_result(
            revision_plan(
                str(arguments.get("topic", "")),
                int(arguments.get("days") or 7),
                str(arguments.get("level", "")),
            )
        )

    if name == "create_lesson_outline":
        return text_result(
            lesson_outline(
                str(arguments.get("topic", "")),
                str(arguments.get("class_level", "")),
                int(arguments.get("duration_minutes") or 45),
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
