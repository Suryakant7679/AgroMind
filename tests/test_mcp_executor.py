from __future__ import annotations

import unittest
from unittest import mock

from app.mcp.executor import explicit_mcp_answer


class ExplicitMCPExecutorTests(unittest.TestCase):
    def test_real_default_tool_is_executed(self) -> None:
        with mock.patch("app.mcp.docker_tools.list_containers", return_value=[{"name": "app", "state": "running"}]) as tool:
            answer = explicit_mcp_answer("use docker MCP docker_containers")
        self.assertIsNotNone(answer)
        text, category = answer
        self.assertEqual(category, "docker")
        self.assertIn('"state": "running"', text)
        tool.assert_called_once_with()

    def test_required_arguments_are_reported(self) -> None:
        answer = explicit_mcp_answer("use filesystem MCP read_file")
        self.assertIsNotNone(answer)
        text, category = answer
        self.assertEqual(category, "filesystem")
        self.assertIn("required arguments are missing: path", text)

    def test_json_arguments_are_passed_to_tool(self) -> None:
        with mock.patch("app.mcp.filesystem_tools.WorkspaceFilesystem.read_file", autospec=True, return_value={"path": "README.md", "content": "ok"}) as tool:
            answer = explicit_mcp_answer('use filesystem MCP read_file with {"path":"README.md"}')
        self.assertIn('"content": "ok"', answer[0])
        tool.assert_called_once_with(mock.ANY, path="README.md")

    def test_unknown_server_lists_categories(self) -> None:
        answer = explicit_mcp_answer("use imaginary MCP tool")
        self.assertEqual(answer[1], "router")
        self.assertIn("Available MCP categories", answer[0])

    def test_python_and_github_remain_on_specialized_executors(self) -> None:
        self.assertIsNone(explicit_mcp_answer("use python MCP tool to give details of langchain"))
        self.assertIsNone(explicit_mcp_answer("use github MCP for https://github.com/o/r"))

    def test_python_run_tool_executes_with_json_arguments(self) -> None:
        answer = explicit_mcp_answer('use python MCP run_python with {"code":"result = 2 + 2"}')
        self.assertEqual(answer[1], "python")
        self.assertIn('"result": 4', answer[0])

    def test_named_github_tool_uses_generic_argument_validation(self) -> None:
        answer = explicit_mcp_answer("use github MCP github_issues")
        self.assertEqual(answer[1], "github")
        self.assertIn("required arguments are missing: owner, repo", answer[0])

if __name__ == "__main__":
    unittest.main()