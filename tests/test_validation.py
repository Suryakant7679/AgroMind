from __future__ import annotations

import unittest
from unittest import mock

from app import llm
from app.model_router import ModelRoute
from app.validation import (
    CodeValidator,
    HallucinationValidator,
    JSONValidator,
    MarkdownValidator,
    PipelineResult,
    ValidationError,
    ValidationManager,
    ValidationResult,
    validation_context,
)


class ResponseValidatorTests(unittest.TestCase):
    def test_default_validator_order_matches_pipeline_contract(self) -> None:
        self.assertEqual(
            [validator.name for validator in ValidationManager().validators],
            [
                "MarkdownValidator",
                "JSONValidator",
                "CodeValidator",
                "ToolOutputValidator",
                "CitationValidator",
                "MissingInformationValidator",
                "HallucinationValidator",
                "SafetyValidator",
                "GrammarValidator",
                "FormattingValidator",
            ],
        )

    def test_markdown_validator_repairs_unclosed_fence(self) -> None:
        result = MarkdownValidator().validate("```python\nprint('ok')", {})
        self.assertFalse(result.passed)
        self.assertEqual(result.corrected_response, "```python\nprint('ok')\n```")

    def test_json_validator_checks_only_explicit_json_responses(self) -> None:
        self.assertTrue(JSONValidator().validate("JSON is a data format.", {}).passed)
        invalid = JSONValidator().validate('{"answer": }', {"expects_json": True})
        self.assertFalse(invalid.passed)
        valid = JSONValidator().validate('```json\n{"answer": 42}\n```', {"expects_json": True})
        self.assertTrue(valid.passed)
        self.assertEqual(valid.corrected_response, '{"answer": 42}')

    def test_code_validator_compiles_python_blocks(self) -> None:
        invalid = CodeValidator().validate("```python\nif True print('x')\n```", {})
        self.assertFalse(invalid.passed)
        self.assertIn("invalid syntax", invalid.issues[0])
        self.assertTrue(CodeValidator().validate("```python\nprint('x')\n```", {}).passed)

    def test_manager_retries_once_with_feedback(self) -> None:
        class RejectFirst:
            name = "RejectFirst"

            def validate(self, response, context):
                return ValidationResult(response == "fixed", 1.0 if response == "fixed" else 0.0, [] if response == "fixed" else ["not fixed"])

        retry = mock.Mock(return_value="fixed")
        manager = ValidationManager([RejectFirst()])
        self.assertEqual(manager.process("bad", retry=retry), "fixed")
        retry.assert_called_once()
        self.assertIn("not fixed", retry.call_args.args[0])

    def test_manager_raises_after_single_failed_retry_without_repair(self) -> None:
        class RejectAll:
            name = "RejectAll"

            def validate(self, response, context):
                return ValidationResult(False, 0.0, ["still invalid"])

        retry = mock.Mock(return_value="also bad")
        with self.assertRaises(ValidationError):
            ValidationManager([RejectAll()]).process("bad", retry=retry)
        retry.assert_called_once()

    def test_manager_uses_available_repair_when_retry_still_fails(self) -> None:
        class RepairOriginal:
            name = "RepairOriginal"

            def validate(self, response, context):
                if response == "bad":
                    return ValidationResult(False, 0.5, ["repairable"], "repaired")
                if response == "repaired":
                    return ValidationResult(True, 1.0, [])
                return ValidationResult(False, 0.0, ["retry failed"])

        result = ValidationManager([RepairOriginal()]).process("bad", retry=lambda feedback: "worse")
        self.assertEqual(result, "repaired")

    def test_enabled_configuration_is_modular(self) -> None:
        manager = ValidationManager(enabled=["JSONValidator", "SafetyValidator"])
        self.assertEqual([item.name for item in manager.validators], ["JSONValidator", "SafetyValidator"])
        with mock.patch.dict("os.environ", {"AIOS_DISABLED_VALIDATORS": "GrammarValidator"}, clear=False):
            self.assertNotIn("GrammarValidator", [item.name for item in ValidationManager.from_env().validators])

    def test_validator_logs_name_result_issues_and_execution_time(self) -> None:
        with self.assertLogs("aios.validation", level="INFO") as captured:
            ValidationManager([MarkdownValidator()]).validate("ok")
        message = captured.output[0]
        self.assertIn("validator=MarkdownValidator", message)
        self.assertIn("passed=True", message)
        self.assertIn("execution_ms=", message)
        self.assertIn("issues=[]", message)

    def test_hallucination_validator_accepts_pluggable_non_regex_detector(self) -> None:
        class Judge:
            name = "llm_judge"

            def check(self, response, context):
                return ValidationResult(False, 0.2, ["unsupported claim"])

        result = HallucinationValidator([Judge()]).validate("A claim", {})
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.2)
        self.assertIn("llm_judge", result.issues[0])

    def test_context_infers_explicit_json_and_citation_requests(self) -> None:
        context = validation_context([{"role": "user", "content": "Return JSON and cite your sources."}])
        self.assertTrue(context["expects_json"])
        self.assertTrue(context["requires_citations"])


    def test_context_does_not_require_citations_for_implicit_rag_instruction(self) -> None:
        context = validation_context(
            [
                {"role": "system", "content": "Cite sources with the bracketed citation labels."},
                {"role": "user", "content": "Summarize the attached PDF."},
            ]
        )
        self.assertFalse(context["requires_citations"])

class LLMValidationIntegrationTests(unittest.TestCase):
    def test_current_year_sports_winner_always_uses_web_search(self) -> None:
        with mock.patch.object(llm, "generate_with_router") as router:
            self.assertTrue(llm.should_use_web_search("who won fifa world cup this year 2026"))
        router.assert_not_called()

    def test_prior_assistant_clarification_is_not_appended_to_new_answer(self) -> None:
        prior = (
            "I understand you'd like me to use web search results when replying. When I'm provided with "
            "information from a web search, I use it to answer your questions.\n\n"
            "Is there something specific you'd like me to search for, or a question you'd like me to answer "
            "using web evidence?"
        )
        generated = f"The current Chief Minister of West Bengal is Suvendu Adhikari.\n\n{prior}"
        messages = [
            {"role": "user", "content": "search web and then reply"},
            {"role": "assistant", "content": prior},
            {"role": "user", "content": "Who is the current chief minister of Bengal? Use web search."},
        ]

        self.assertEqual(
            llm.remove_echoed_assistant_responses(generated, messages),
            "The current Chief Minister of West Bengal is Suvendu Adhikari.",
        )

    def test_non_streaming_response_is_validated_and_retried_once(self) -> None:
        route = ModelRoute("general", "openai", "test-model")
        manager = mock.Mock()
        manager.process.side_effect = lambda response, context, retry: retry("fix it")
        with (
            mock.patch.object(llm, "VALIDATION", manager),
            mock.patch.object(llm, "generate_with_router", side_effect=[("bad", route), ("good", route)]) as generate,
            mock.patch.object(llm.USAGE, "record"),
        ):
            response, provider = llm.generate_response([{"role": "user", "content": "hello"}])
        self.assertEqual((response, provider), ("good", "openai"))
        self.assertEqual(generate.call_count, 2)
        retry_messages = generate.call_args_list[1].args[0]
        self.assertEqual(retry_messages[-1], {"role": "system", "content": "fix it"})

    def test_live_tool_plan_is_regenerated_before_delivery(self) -> None:
        route = ModelRoute("research", "groq", "test-model")
        messages = [
            {"role": "system", "content": "AUTHORITATIVE LIVE WEB EVIDENCE\nURL: https://example.com/current"},
            {"role": "user", "content": "Who is current?"},
        ]
        with (
            mock.patch.object(
                llm,
                "_generate_response_once",
                side_effect=[
                    ("I will perform a quick search.\n\nDuckDuckGo Search: current", route),
                    ("The current office holder is Person. [Official source](https://example.com/current)", route),
                ],
            ) as generate,
            mock.patch.object(llm, "VALIDATION") as validation,
        ):
            validation.process.side_effect = lambda text, *_args, **_kwargs: text
            chunks, provider = llm.generate_response_stream(messages)
        self.assertEqual(provider, "groq")
        self.assertIn("Official source", "".join(chunks))
        self.assertEqual(generate.call_count, 2)

    def test_stream_is_forwarded_incrementally_without_full_response_buffering(self) -> None:
        route = ModelRoute("general", "openai", "test-model")
        manager = mock.Mock()
        manager.process.return_value = "validated"
        with (
            mock.patch.object(llm, "VALIDATION", manager),
            mock.patch.object(llm, "generate_with_router", return_value=(iter(["raw", " text"]), route)),
            mock.patch.object(llm.USAGE, "record"),
        ):
            chunks, provider = llm.generate_response_stream([{"role": "user", "content": "hello"}])
        self.assertEqual(provider, "openai")
        self.assertEqual(list(chunks), ["raw", " text"] )
        manager.process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
