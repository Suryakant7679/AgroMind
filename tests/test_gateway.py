from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.gateway import (
    AUTH_RESPONSE_SCHEMA,
    CHAT_SCHEMA,
    GatewayError,
    GatewayStore,
    JWTService,
    PostgreSQLGatewayStore,
    Principal,
    bearer_token,
    normalize_api_path,
    password_hash,
    password_matches,
    require_owner,
    create_gateway_store,
)
from app.store import ConversationStore
from app.redis_state import NullRedisState


class JWTServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jwt = JWTService("a-secure-test-secret-that-is-at-least-32-bytes", ttl_seconds=60)
        self.principal = Principal("user-1", "user@example.com", ("user",), "session-1")

    def test_issues_and_verifies_all_identity_claims(self) -> None:
        token = self.jwt.issue(self.principal, now=100)
        self.assertEqual(self.jwt.verify(token, now=120), self.principal)

    def test_rejects_tampering_and_expiration(self) -> None:
        token = self.jwt.issue(self.principal, now=100)
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        with self.assertRaisesRegex(GatewayError, "signature"):
            self.jwt.verify(".".join(parts), now=120)
        with self.assertRaisesRegex(GatewayError, "expired"):
            self.jwt.verify(token, now=160)

    def test_rejects_wrong_issuer_or_audience(self) -> None:
        token = self.jwt.issue(self.principal, now=100)
        other = JWTService("a-secure-test-secret-that-is-at-least-32-bytes", issuer="other")
        with self.assertRaisesRegex(GatewayError, "issuer or audience"):
            other.verify(token, now=120)


class GatewayModelTests(unittest.TestCase):
    def test_local_rate_limiter_enforces_limits_without_redis(self) -> None:
        state = NullRedisState()
        self.assertTrue(state.rate_limit("private-id", 2, 60)["allowed"])
        self.assertTrue(state.rate_limit("private-id", 2, 60)["allowed"])
        blocked = state.rate_limit("private-id", 2, 60)
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["backend"], "memory")
        self.assertTrue(all("private-id" not in key for key in state._rate_buckets))

    def test_passwords_use_salted_pbkdf2_hashes(self) -> None:
        first = password_hash("correct horse battery staple")
        second = password_hash("correct horse battery staple")
        self.assertNotEqual(first, second)
        self.assertTrue(password_matches("correct horse battery staple", first))
        self.assertFalse(password_matches("incorrect", first))
        with self.assertRaisesRegex(GatewayError, "at least 8"):
            password_hash("short")

    def test_request_and_response_schemas_are_strict(self) -> None:
        valid = CHAT_SCHEMA.validate({"message": "hello", "stream": True})
        self.assertEqual(valid["message"], "hello")
        with self.assertRaises(GatewayError) as caught:
            CHAT_SCHEMA.validate({"message": "", "unexpected": 1})
        self.assertEqual(caught.exception.code, "schema_validation_failed")
        with self.assertRaises(GatewayError) as response_error:
            AUTH_RESPONSE_SCHEMA.validate({"access_token": "token"})
        self.assertEqual(response_error.exception.code, "invalid_response")

    def test_api_version_normalization_and_bearer_parsing(self) -> None:
        self.assertEqual(normalize_api_path("/api/v1/session"), ("/api/session", "1"))
        self.assertEqual(normalize_api_path("/api/session"), ("/api/session", "1"))
        with self.assertRaises(GatewayError) as caught:
            normalize_api_path("/api/v2/session")
        self.assertEqual(caught.exception.code, "unsupported_api_version")
        self.assertEqual(bearer_token("Bearer abc.def.ghi"), "abc.def.ghi")
        with self.assertRaises(GatewayError):
            bearer_token("Basic value")

    def test_owner_authorization_allows_owner_and_admin_only(self) -> None:
        resource = {"user_id": "owner"}
        require_owner(resource, Principal("owner", "owner@example.com"))
        require_owner(resource, Principal("admin", "admin@example.com", ("admin",)))
        with self.assertRaises(GatewayError) as caught:
            require_owner(resource, Principal("other", "other@example.com"))
        self.assertEqual(caught.exception.status, 403)


class GatewayStoreTests(unittest.TestCase):
    def test_factory_selects_postgres_when_database_storage_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            "os.environ",
            {"AIOS_STORAGE_BACKEND": "postgres", "DATABASE_URL": "postgresql://localhost/aios"},
        ):
            self.assertIsInstance(create_gateway_store(Path(temp_dir)), PostgreSQLGatewayStore)

    def test_users_secret_and_analytics_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gateway.json"
            store = GatewayStore(path)
            secret = store.jwt_secret()
            user = store.register("User@Example.com", "strong-password", "User")
            authenticated = store.authenticate("user@example.com", "strong-password")
            self.assertEqual(authenticated["id"], user["id"])
            self.assertNotIn("password_hash", authenticated)
            store.record_event({"event_name": "api_request", "status_code": 200})
            reloaded = GatewayStore(path)
            self.assertEqual(reloaded.jwt_secret(), secret)
            self.assertEqual(reloaded.get_user(user["id"])["email"], "user@example.com")
            self.assertEqual(reloaded.analytics()[0]["event_name"], "api_request")

    def test_duplicate_users_and_invalid_credentials_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GatewayStore(Path(temp_dir) / "gateway.json")
            store.register("user@example.com", "strong-password")
            with self.assertRaises(GatewayError) as duplicate:
                store.register("USER@example.com", "another-password")
            self.assertEqual(duplicate.exception.status, 409)
            with self.assertRaises(GatewayError) as invalid:
                store.authenticate("user@example.com", "wrong-password")
            self.assertEqual(invalid.exception.status, 401)


class GatewayHTTPIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from app import main

        self.main = main
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = (main.STORE, main.GATEWAY_STORE, main.JWT, main.AUTH_REQUIRED, main.REDIS)
        main.STORE = ConversationStore(root / "conversations.json")
        main.GATEWAY_STORE = GatewayStore(root / "gateway.json")
        main.JWT = JWTService(main.GATEWAY_STORE.jwt_secret(), ttl_seconds=300)
        main.AUTH_REQUIRED = True
        main.REDIS = NullRedisState()
        self.server = main.ThreadingHTTPServer(("127.0.0.1", 0), main.AIOSHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.main.STORE, self.main.GATEWAY_STORE, self.main.JWT, self.main.AUTH_REQUIRED, self.main.REDIS = self.originals
        self.temp.cleanup()

    def request(self, method: str, path: str, payload=None, token: str = ""):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read().decode())
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def register(self, email: str) -> dict:
        status, _, body = self.request("POST", "/api/v1/auth/register", {"email": email, "password": "strong-password", "display_name": "Test"})
        self.assertEqual(status, 201)
        return body

    def test_versioned_auth_creates_durable_session_and_identity(self) -> None:
        status, headers, error = self.request("GET", "/api/v1/session")
        self.assertEqual(status, 401)
        self.assertEqual(error["error"]["code"], "authentication_required")
        self.assertIn("X-Request-Id", headers)
        self.assertEqual(headers["X-API-Version"], "1")

        registered = self.register("one@example.com")
        token = registered["access_token"]
        status, headers, me = self.request("GET", "/api/v1/auth/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(me["user"]["email"], "one@example.com")
        self.assertIn("X-RateLimit-Limit", headers)

        reloaded = ConversationStore(Path(self.temp.name) / "conversations.json")
        sessions = reloaded._load()["sessions"]
        self.assertEqual(sessions[0]["user_id"], registered["user"]["id"])
        self.assertGreaterEqual(len(self.main.GATEWAY_STORE.analytics()), 3)

    def test_conversation_authorization_blocks_another_user(self) -> None:
        first = self.register("first@example.com")
        second = self.register("second@example.com")
        status, _, conversation = self.request("POST", "/api/v1/conversations", {}, first["access_token"])
        self.assertEqual(status, 201)
        self.assertEqual(conversation["user_id"], first["user"]["id"])
        status, _, error = self.request("GET", f"/api/v1/conversations/{conversation['id']}", token=second["access_token"])
        self.assertEqual(status, 403)
        self.assertEqual(error["error"]["code"], "forbidden")

    def test_conversation_owner_can_rename_and_delete_chat(self) -> None:
        first = self.register("mutate-one@example.com")
        second = self.register("mutate-two@example.com")
        _, _, conversation = self.request("POST", "/api/v1/conversations", {}, first["access_token"])
        path = f"/api/v1/conversations/{conversation['id']}"

        status, _, error = self.request("PATCH", path, {"title": "Not allowed"}, second["access_token"])
        self.assertEqual(status, 403)
        self.assertEqual(error["error"]["code"], "forbidden")

        status, _, renamed = self.request("PATCH", path, {"title": "Renamed study chat"}, first["access_token"])
        self.assertEqual(status, 200)
        self.assertEqual(renamed["conversation"]["title"], "Renamed study chat")

        status, _, deleted = self.request("DELETE", path, token=first["access_token"])
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        status, _, error = self.request("GET", path, token=first["access_token"])
        self.assertEqual(status, 404)

    def test_semantic_chat_search_is_scoped_to_authenticated_user(self) -> None:
        first = self.register("search-one@example.com")
        second = self.register("search-two@example.com")
        _, _, first_chat = self.request("POST", "/api/v1/conversations", {}, first["access_token"])
        self.request("POST", "/api/v1/conversations", {}, second["access_token"])
        expected = [{
            "conversation_id": first_chat["id"],
            "title": "Vector memory",
            "snippet": "We discussed semantic retrieval.",
            "score": 0.9,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }]
        with (
            mock.patch.object(self.main, "index_conversation_history") as index_history,
            mock.patch.object(self.main, "related_conversations", return_value=expected) as search,
        ):
            status, _, payload = self.request(
                "GET",
                "/api/v1/conversations/search?q=meaning+based+memory&top_k=3",
                token=first["access_token"],
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], expected)
        indexed = index_history.call_args.args[0]
        self.assertEqual([item["id"] for item in indexed], [first_chat["id"]])
        search.assert_called_once_with(
            "meaning based memory",
            indexed,
            top_k=3,
            user_id=first["user"]["id"],
        )
    def test_long_term_memory_is_scoped_to_authenticated_user(self) -> None:
        first = self.register("memory-one@example.com")
        second = self.register("memory-two@example.com")
        status, _, _ = self.request(
            "POST", "/api/v1/memory", {"learned_behavior": ["prefers concise answers"]}, first["access_token"]
        )
        self.assertEqual(status, 200)
        status, _, second_memory = self.request("GET", "/api/v1/memory", token=second["access_token"])
        self.assertEqual(status, 200)
        self.assertEqual(second_memory["memory"]["learned_behavior"], [])

    def test_observability_dashboard_is_available_locally_and_admin_protected(self) -> None:
        self.main.AUTH_REQUIRED = False
        status, _, payload = self.request("GET", "/api/v1/observability")
        self.assertEqual(status, 200)
        dashboard = payload["observability"]
        self.assertTrue({"tokens", "cost", "api", "models", "tools", "resources", "gpu", "queues", "health"} <= set(dashboard))

        self.main.AUTH_REQUIRED = True
        user = self.register("dashboard-user@example.com")
        status, _, error = self.request("GET", "/api/v1/observability", token=user["access_token"])
        self.assertEqual(status, 403)
        self.assertEqual(error["error"]["code"], "forbidden")
    def test_unsupported_version_returns_json_error(self) -> None:
        status, _, body = self.request("GET", "/api/v2/health")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "unsupported_api_version")

    def test_foreign_attachment_is_rejected_before_chat_is_created(self) -> None:
        user = self.register("attachment@example.com")
        with mock.patch.object(self.main, "list_artifacts", return_value=[{"id": "private", "user_id": "another-user"}]):
            status, _, body = self.request("POST", "/api/v1/chat", {"message": "summarize", "artifact_ids": ["private"]}, user["access_token"])
        self.assertEqual(status, 403)
        self.assertEqual(self.main.STORE.list_conversations(), [])

    def test_unknown_attachment_is_rejected(self) -> None:
        user = self.register("missing-attachment@example.com")
        with mock.patch.object(self.main, "list_artifacts", return_value=[]):
            status, _, body = self.request("POST", "/api/v1/chat", {"message": "summarize", "artifact_ids": ["missing"]}, user["access_token"])
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "artifact_not_found")

    def test_orchestration_requires_admin_before_invocation(self) -> None:
        user = self.register("orchestrate@example.com")
        with mock.patch.object(self.main.ORCHESTRATOR, "invoke") as invoke:
            status, _, _ = self.request("POST", "/api/v1/orchestrate", {"objective": "read files"}, user["access_token"])
        self.assertEqual(status, 403)
        invoke.assert_not_called()

    def test_chat_mcp_returns_result_without_model_call(self) -> None:
        user = self.register("mcp@example.com")
        with (mock.patch("app.mcp.duckduckgo_tools.search_web", autospec=True, return_value=[{"title": "Verified source"}]) as search,
              mock.patch.object(self.main, "generate_response", side_effect=AssertionError("LLM should not run"))):
            status, _, body = self.request("POST", "/api/v1/chat", {"message": 'use duckduckgo MCP duckduckgo_search {"query":"algebra"}'}, user["access_token"])
        self.assertEqual(status, 200)
        self.assertEqual(body["provider"], "duckduckgo-mcp")
        self.assertIn("Verified source", body["message"]["content"])
        search.assert_called_once_with(query="algebra")
        chat = self.main.STORE.get_conversation(body["conversation_id"])
        self.assertEqual(chat["recovery_state"]["status"], "complete")

    def test_non_admin_chat_cannot_initialize_filesystem_tool(self) -> None:
        user = self.register("restricted-mcp@example.com")
        with mock.patch("app.mcp.executor._registry") as registry:
            status, _, body = self.request("POST", "/api/v1/chat", {"message": 'use filesystem MCP read_file {"path":"data/uploads.json"}'}, user["access_token"])
        self.assertEqual(status, 200)
        self.assertIn("administrator", body["message"]["content"])
        registry.assert_not_called()

    def test_model_failure_marks_chat_failed(self) -> None:
        user = self.register("failed-chat@example.com")
        with (mock.patch.object(self.main, "build_context_messages", return_value=[]) as context,
              mock.patch.object(self.main, "generate_response", side_effect=self.main.LLMError("provider unavailable"))):
            status, _, _ = self.request("POST", "/api/v1/chat", {"message": "hello"}, user["access_token"])
        self.assertEqual(status, 502)
        self.assertFalse(context.call_args.kwargs["allow_workspace"])
        self.assertEqual(self.main.STORE.list_conversations()[0]["recovery_state"]["status"], "failed")

    def test_gateway_rate_limit_returns_structured_429(self) -> None:
        delegate = self.main.REDIS

        class LimitedRedis:
            def rate_limit(self, identity, limit, window, scope):
                return {"allowed": False, "limit": limit, "remaining": 0, "retry_after": window}

            def __getattr__(self, name):
                return getattr(delegate, name)

        self.main.REDIS = LimitedRedis()
        status, headers, payload = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"]["code"], "rate_limit_exceeded")
        self.assertIn("Retry-After", headers)


if __name__ == "__main__":
    unittest.main()
