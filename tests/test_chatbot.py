from fastapi.testclient import TestClient

import agromind.main as main
import agromind.supabase_store as store
from agromind.chatbot import WorkspaceChatRequest, WorkspaceChatResponse, WorkspaceChatbot


def test_chatbot_page_requires_login():
    with TestClient(main.app) as test_client:
        response = test_client.get("/chatbot", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_chatbot_page_renders_for_authenticated_user(monkeypatch):
    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "user-1", "email": "u@example.com"})
    monkeypatch.delenv("AI_TUTOR_URL", raising=False)

    with TestClient(main.app) as test_client:
        response = test_client.get("/chatbot")

    assert response.status_code == 200
    assert "AI Tutor Chatbot" in response.text
    assert "https://ai-tutor-eta-ochre.vercel.app" in response.text


def test_chatbot_api_requires_login():
    with TestClient(main.app) as test_client:
        response = test_client.post("/api/chatbot/chat", json={"message": "What did I use?"})

    assert response.status_code == 401


def test_chatbot_api_uses_authenticated_workspace_chatbot(monkeypatch):
    class FakeWorkspaceChatbot:
        async def reply(self, request, user_id, access_token=None):
            assert request.message == "What tools did I use?"
            assert request.session_id == "s1"
            assert user_id == "user-1"
            assert access_token == "token"
            return WorkspaceChatResponse(
                session_id="s1",
                answer="You used education tools.",
                provider="local",
                context_items=["Education AI / YouTube Learning Tool"],
            )

    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "user-1", "email": "u@example.com", "access_token": "token"})
    monkeypatch.setattr(main, "workspace_chatbot", FakeWorkspaceChatbot())

    with TestClient(main.app) as test_client:
        response = test_client.post(
            "/api/chatbot/chat",
            json={"message": "What tools did I use?", "session_id": "s1"},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == "You used education tools."
    assert response.json()["context_items"] == ["Education AI / YouTube Learning Tool"]


def test_workspace_chatbot_fallback_uses_recent_outputs(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(store, "fetch_agent_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        store,
        "fetch_recent_outputs",
        lambda *args, **kwargs: [
            {
                "domain": "education",
                "tool": "youtube-learning-tool",
                "prompt": {"goal": "notes"},
                "output_markdown": "Generated study notes.",
            }
        ],
    )
    monkeypatch.setattr(
        store,
        "usage_summary",
        lambda *args, **kwargs: {
            "requests_today": 1,
            "requests_this_month": 1,
            "tokens_this_month": 120,
            "credits_this_month": 1,
            "domain_rows": {"education": {"requests": 1}},
            "provider_rows": {"groq:test": {"requests": 1}},
        },
    )
    saved_messages = []
    monkeypatch.setattr(store, "save_agent_memory", lambda *args, **kwargs: saved_messages.append(args))

    chatbot = WorkspaceChatbot()
    response = __import__("asyncio").run(
        chatbot.reply(
            WorkspaceChatRequest(message="What did I use?", session_id="s1"),
            user_id="user-1",
        )
    )

    assert response.provider == "local"
    assert response.context_items == ["Education AI / YouTube Learning Tool"]
    assert "Education AI / YouTube Learning Tool" in response.answer
    assert len(saved_messages) == 2
