import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import main
from app.mcp.executor import explicit_mcp_answer
from app.mcp.filesystem_tools import WorkspaceFilesystem


class BugRegressionTests(unittest.TestCase):
    def test_remembered_attachments_are_filtered_by_owner(self):
        records = [{"id": "other", "user_id": "other", "cleaned_text": "SECRET"},
                   {"id": "mine", "user_id": "me", "cleaned_text": "MY NOTES"}]
        with mock.patch.object(main, "list_artifacts", return_value=records):
            text = main.uploaded_files_context_text(["other", "mine"], user_id="me")
        self.assertNotIn("SECRET", text)
        self.assertIn("MY NOTES", text)

    def test_untrusted_context_does_not_read_backend_workspace(self):
        with (mock.patch.object(main, "open_files_context_text") as files,
              mock.patch.object(main, "git_status_context_text") as git,
              mock.patch.object(main, "github_context_text", return_value=""),
              mock.patch.object(main, "retrieved_context_text", return_value="")):
            main.context_sections({"active_file": "data/uploads.json"}, [], web_research="", allow_workspace=False)
        files.assert_not_called()
        git.assert_not_called()

    def test_secret_variants_are_excluded_from_reads_lists_and_search(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (".env.production", ".ENV.local", ".ENV"):
                (root / name).write_text("secret-marker", encoding="utf-8")
            (root / "notes.txt").write_text("safe", encoding="utf-8")
            files = WorkspaceFilesystem(root)
            for name in (".env.production", ".ENV.local", ".ENV"):
                with self.assertRaises(ValueError):
                    files.read_file(name)
            self.assertEqual([item["path"] for item in files.list_files()], ["notes.txt"])
            self.assertEqual(files.search_text("secret-marker"), [])

    def test_search_does_not_follow_symlink_outside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            root.mkdir()
            outside = Path(directory) / "private.txt"
            outside.write_text("secret-marker", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(outside)
            except OSError:
                self.skipTest("OS does not permit symlink creation")
            files = WorkspaceFilesystem(root)
            self.assertEqual(files.search_text("secret-marker"), [])
            self.assertEqual(files.list_files(), [])

    def test_mcp_initialization_error_is_reported(self):
        with mock.patch("app.mcp.executor._registry", side_effect=RuntimeError("missing config")):
            result = explicit_mcp_answer("use postgresql MCP postgres_tables")
        self.assertIn("could not initialize", result[0])

    def test_stream_error_updates_persistent_and_redis_recovery(self):
        handler = object.__new__(main.AIOSHandler)
        handler.principal = None
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.write_ndjson_event = mock.Mock()
        handler.record_analytics = mock.Mock()
        with (mock.patch.object(main, "STORE") as store,
              mock.patch.object(main, "REDIS") as redis,
              mock.patch.object(main, "generate_response_stream", side_effect=main.LLMError("offline"))):
            handler.send_chat_stream("session", "chat", "main", [], 0, 4000)
        self.assertEqual(store.set_recovery_state.call_args.args[1]["status"], "failed")
        self.assertEqual(redis.set_stream_state.call_args.args[1]["status"], "failed")

    def test_tool_stream_delivers_and_persists_real_output(self):
        handler = object.__new__(main.AIOSHandler)
        handler.principal = None
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler.write_ndjson_event = mock.Mock()
        handler.record_analytics = mock.Mock()
        with (mock.patch.object(main, "STORE") as store,
              mock.patch.object(main, "REDIS"),
              mock.patch.object(main, "upsert_vector_records"),
              mock.patch.object(main, "vector_record_for_message")):
            handler.send_tool_chat_stream("session", "chat", "main", "Tool answer", "duckduckgo-mcp", "duckduckgo")
        events = [call.args[0] for call in handler.write_ndjson_event.call_args_list]
        self.assertEqual("".join(e["content"] for e in events if e["type"] == "delta"), "Tool answer")
        self.assertEqual(events[-1]["type"], "done")
        store.add_message.assert_called_once_with("chat", "assistant", "Tool answer", thread_id="main")
