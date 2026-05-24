import sys
from types import ModuleType

from agromind.ai import extract_youtube_video_id, fetch_youtube_transcript_text


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
