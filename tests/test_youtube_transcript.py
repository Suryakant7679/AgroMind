import asyncio
import sys
from types import ModuleType

import agromind.ai as ai
from agromind.ai import (
    extract_pdf_text,
    YOUTUBE_TRANSCRIPT_MAX_CHARS,
    extract_youtube_video_id,
    fetch_youtube_transcript_text,
    generate_ai_response,
    truncate_youtube_transcript,
)


class Snippet:
    def __init__(self, text):
        self.text = text


class FakeTranscript:
    def __init__(self, snippets):
        self.snippets = snippets

    def fetch(self):
        return self.snippets


class FakeTranscriptList:
    def __init__(self):
        self.available = [FakeTranscript([Snippet("Fallback"), Snippet("caption text")])]

    def find_transcript(self, languages):
        raise RuntimeError("preferred languages missing")

    def find_generated_transcript(self, languages):
        raise RuntimeError("generated preferred languages missing")

    def find_manually_created_transcript(self, languages):
        raise RuntimeError("manual preferred languages missing")

    def __iter__(self):
        return iter(self.available)


class FakeNewYouTubeTranscriptApi:
    def fetch(self, video_id, languages=None):
        return [Snippet("Direct"), Snippet("transcript")]

    def list(self, video_id):
        return FakeTranscriptList()


class FakeFallbackYouTubeTranscriptApi(FakeNewYouTubeTranscriptApi):
    def fetch(self, video_id, languages=None):
        raise RuntimeError("direct fetch failed")


def install_fake_youtube_module(monkeypatch, api_class):
    module = ModuleType("youtube_transcript_api")
    module.YouTubeTranscriptApi = api_class
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", module)


def test_extract_youtube_video_id_handles_common_link_formats():
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ?si=test") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_fetch_youtube_transcript_text_uses_new_api_direct_fetch(monkeypatch):
    install_fake_youtube_module(monkeypatch, FakeNewYouTubeTranscriptApi)

    assert fetch_youtube_transcript_text("dQw4w9WgXcQ") == "Direct transcript"


def test_fetch_youtube_transcript_text_falls_back_to_any_available_caption(monkeypatch):
    install_fake_youtube_module(monkeypatch, FakeFallbackYouTubeTranscriptApi)

    assert fetch_youtube_transcript_text("dQw4w9WgXcQ") == "Fallback caption text"


def test_truncate_youtube_transcript_limits_large_prompts():
    transcript = "word " * (YOUTUBE_TRANSCRIPT_MAX_CHARS // 2)

    trimmed, was_truncated = truncate_youtube_transcript(transcript)

    assert was_truncated is True
    assert len(trimmed) <= YOUTUBE_TRANSCRIPT_MAX_CHARS


def test_extract_pdf_text_reads_selectable_pdf_content():
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Photosynthesis converts light energy into chemical energy.")
    content = doc.write()
    doc.close()

    extracted = extract_pdf_text(content)

    assert "Photosynthesis converts light energy into chemical energy." in extracted
    assert "--- Page 1 ---" in extracted


def test_youtube_generation_falls_back_when_transcript_unavailable(monkeypatch):
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ai, "fetch_youtube_transcript_text", lambda video_id: None)
    monkeypatch.setattr(ai, "fetch_youtube_video_title", lambda url: "Readable Video Title")

    output, provider, language = asyncio.run(
        generate_ai_response(
            "education",
            "youtube-learning-tool",
            {"url": "https://youtu.be/dQw4w9WgXcQ", "goal": "Notes"},
            None,
            "en-US",
            "starter",
        )
    )

    assert provider == "local"
    assert language == "en-US"
    assert "Readable Video Title" in output
    assert "transcript could not be retrieved" in output
