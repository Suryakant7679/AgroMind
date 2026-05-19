import re

from fastapi.testclient import TestClient

import agromind.main as main


def client():
    return TestClient(main.app)


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token was not rendered"
    return match.group(1)


def test_public_home_and_auth_pages_render():
    with client() as test_client:
        assert test_client.get("/").status_code == 200
        assert test_client.get("/login").status_code == 200
        assert test_client.get("/signup").status_code == 200


def test_dashboard_requires_login():
    with client() as test_client:
        response = test_client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


def test_login_rejects_bad_csrf():
    with client() as test_client:
        response = test_client.post(
            "/login",
            data={"email": "user@example.com", "password": "password", "csrf_token": "bad", "next": "/dashboard"},
        )
        assert response.status_code == 403


def test_signup_uses_verification_flow(monkeypatch):
    monkeypatch.setattr(main, "supabase_auth_configured", lambda: True)
    monkeypatch.setattr(
        main,
        "sign_up_with_password",
        lambda email, password, full_name: {"id": "user-1", "email": email, "access_token": None},
    )
    monkeypatch.setattr(main, "insert_profile_if_missing", lambda user_id, email, full_name: None)

    with client() as test_client:
        signup_page = test_client.get("/signup")
        token = csrf_from(signup_page.text)
        response = test_client.post(
            "/signup",
            data={
                "full_name": "AgroMind User",
                "email": "new@example.com",
                "password": "secret123",
                "csrf_token": token,
                "next": "/dashboard",
            },
        )

    assert response.status_code == 200
    assert "Check your email" in response.text


def test_authenticated_dashboard_renders(monkeypatch):
    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "user-1", "email": "u@example.com"})
    monkeypatch.setattr(main, "fetch_recent_outputs", lambda user_id, access_token=None: [])

    with client() as test_client:
        response = test_client.get("/dashboard")
        assert response.status_code == 200
        assert "Dashboard" in response.text


def test_admin_requires_admin_profile(monkeypatch):
    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "user-1", "email": "u@example.com"})
    monkeypatch.setattr(main, "fetch_profile", lambda user_id, access_token=None: {"role": "member"})

    with client() as test_client:
        response = test_client.get("/admin", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"


def test_admin_page_uses_profiles(monkeypatch):
    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "admin-1", "email": "admin@example.com"})
    monkeypatch.setattr(main, "fetch_profile", lambda user_id, access_token=None: {"role": "admin"})
    monkeypatch.setattr(
        main,
        "fetch_profiles",
        lambda: [{"email": "member@example.com", "full_name": "Member User", "role": "member", "plan": "starter"}],
    )

    with client() as test_client:
        response = test_client.get("/admin")
        assert response.status_code == 200
        assert "Member User" in response.text
