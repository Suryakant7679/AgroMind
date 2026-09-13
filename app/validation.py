from __future__ import annotations

import ast
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence


LOGGER = logging.getLogger("aios.validation")


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    score: float
    issues: list[str] = field(default_factory=list)
    corrected_response: str | None = None


class Validator(Protocol):
    name: str

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult: ...


class ValidationError(RuntimeError):
    """Raised when an LLM response cannot be made safe and valid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = list(issues)
        super().__init__("Response validation failed: " + "; ".join(self.issues))


@dataclass(frozen=True)
class PipelineResult:
    response: str
    passed: bool
    results: list[ValidationResult]
    failed_validators: list[str]

    @property
    def issues(self) -> list[str]:
        return [issue for result in self.results for issue in result.issues]


def _result(issues: list[str], corrected: str | None = None, score: float | None = None) -> ValidationResult:
    passed = not issues
    return ValidationResult(passed, 1.0 if passed else (score if score is not None else 0.0), issues, corrected)


class MarkdownValidator:
    name = "MarkdownValidator"

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        issues: list[str] = []
        corrected: str | None = None
        if response.count("```") % 2:
            issues.append("Markdown contains an unclosed fenced code block.")
            corrected = response.rstrip() + "\n```"
        malformed_links = re.findall(r"\[[^\]]+\]\([^\s)]*$", response, re.MULTILINE)
        if malformed_links:
            issues.append("Markdown contains an unclosed link target.")
        return _result(issues, corrected, 0.5)


class JSONValidator:
    name = "JSONValidator"

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        if not context.get("expects_json"):
            return _result([])
        candidate = response.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", candidate, re.DOTALL | re.IGNORECASE)
        corrected = fenced.group(1).strip() if fenced else None
        candidate = corrected or candidate
        try:
            json.loads(candidate)
        except json.JSONDecodeError as exc:
            return _result([f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."], corrected, 0.0)
        return _result([], corrected)


class CodeValidator:
    name = "CodeValidator"
    _fence = re.compile(r"```([\w.+-]*)\s*\n(.*?)```", re.DOTALL)

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        issues: list[str] = []
        blocks = self._fence.findall(response)
        for language, code in blocks:
            if language.lower() in {"py", "python"}:
                try:
                    ast.parse(code)
                except SyntaxError as exc:
                    issues.append(f"Python code block has invalid syntax at line {exc.lineno}: {exc.msg}.")
        if context.get("expects_python") and not blocks:
            try:
                ast.parse(response)
            except SyntaxError as exc:
                issues.append(f"Requested Python response has invalid syntax at line {exc.lineno}: {exc.msg}.")
        return _result(issues)


class ToolOutputValidator:
    name = "ToolOutputValidator"

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        required = [str(value) for value in context.get("required_tool_output", []) if str(value).strip()]
        missing = [value for value in required if value not in response]
        issues = [f"Required tool output is not represented: {value[:120]}" for value in missing]
        return _result(issues)


class CitationValidator:
    name = "CitationValidator"
    _citation = re.compile(r"\[[^\]]+\]\(https?://[^)]+\)")

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        if context.get("requires_citations") and not self._citation.search(response):
            return _result(["The response requires citations but contains none."])
        return _result([])


class MissingInformationValidator:
    name = "MissingInformationValidator"

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        required = [str(item).strip() for item in context.get("required_information", []) if str(item).strip()]
        normalized = response.casefold()
        missing = [item for item in required if item.casefold() not in normalized]
        return _result([f"Required information is missing: {item}" for item in missing])


class HallucinationDetector(Protocol):
    name: str

    def check(self, response: str, context: Mapping[str, Any]) -> ValidationResult: ...


class ContextGroundingDetector:
    """Checks explicit factual claims against supplied evidence.

    This deterministic implementation is one optional strategy. LLM judges, RAG,
    web-search, and knowledge-graph implementations can satisfy the same protocol.
    """

    name = "context_grounding"

    def check(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        evidence = [str(item) for item in context.get("grounding_evidence", [])]
        claims = [str(item) for item in context.get("claims_to_verify", [])]
        if not claims:
            return _result([])
        evidence_terms = {term.casefold() for item in evidence for term in re.findall(r"[\w.-]{3,}", item)}
        unsupported: list[str] = []
        for claim in claims:
            terms = {term.casefold() for term in re.findall(r"[\w.-]{3,}", claim)}
            if terms and len(terms & evidence_terms) / len(terms) < 0.6:
                unsupported.append(claim)
        return _result([f"Claim is not supported by supplied evidence: {claim}" for claim in unsupported])


class HallucinationValidator:
    name = "HallucinationValidator"

    def __init__(self, detectors: Sequence[HallucinationDetector] | None = None) -> None:
        self.detectors = list(detectors or [ContextGroundingDetector()])

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        results = [detector.check(response, context) for detector in self.detectors]
        issues = [f"{detector.name}: {issue}" for detector, result in zip(self.detectors, results) for issue in result.issues]
        score = min((result.score for result in results), default=1.0)
        return _result(issues, score=score)


class SafetyValidator:
    name = "SafetyValidator"
    _dangerous = re.compile(
        r"\b(?:disable antivirus|steal (?:passwords?|credentials?)|deploy ransomware|make a bomb)\b",
        re.IGNORECASE,
    )

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        refusal = re.search(r"\b(?:can't|cannot|won't|will not|refuse|not able to)\b", response, re.IGNORECASE)
        if self._dangerous.search(response) and not refusal:
            return _result(["Response contains actionable high-risk harmful instructions."])
        return _result([])


class GrammarValidator:
    name = "GrammarValidator"
    _repeated_word = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.IGNORECASE)

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        corrected = self._repeated_word.sub(r"\1", response)
        if corrected != response:
            return _result(["Response contains an accidentally repeated word."], corrected, 0.8)
        return _result([])


class FormattingValidator:
    name = "FormattingValidator"

    def validate(self, response: str, context: Mapping[str, Any]) -> ValidationResult:
        corrected = "\n".join(line.rstrip() for line in response.strip().splitlines())
        corrected = re.sub(r"\n{4,}", "\n\n\n", corrected)
        if not corrected:
            return _result(["Response is empty."])
        if corrected != response:
            return _result(["Response contains inconsistent surrounding whitespace or blank lines."], corrected, 0.9)
        return _result([])


VALIDATOR_TYPES: tuple[type[Validator], ...] = (
    MarkdownValidator,
    JSONValidator,
    CodeValidator,
    ToolOutputValidator,
    CitationValidator,
    MissingInformationValidator,
    HallucinationValidator,
    SafetyValidator,
    GrammarValidator,
    FormattingValidator,
)


class ValidationManager:
    def __init__(self, validators: Sequence[Validator] | None = None, enabled: Sequence[str] | None = None) -> None:
        validators = list(validators) if validators is not None else [validator_type() for validator_type in VALIDATOR_TYPES]
        enabled_names = {name.casefold() for name in enabled} if enabled is not None else None
        self.validators = [validator for validator in validators if enabled_names is None or validator.name.casefold() in enabled_names]

    @classmethod
    def from_env(cls) -> "ValidationManager":
        configured = os.getenv("AIOS_ENABLED_VALIDATORS", "").strip()
        disabled = {item.strip().casefold() for item in os.getenv("AIOS_DISABLED_VALIDATORS", "").split(",") if item.strip()}
        enabled = [item.strip() for item in configured.split(",") if item.strip()] if configured else None
        manager = cls(enabled=enabled)
        manager.validators = [validator for validator in manager.validators if validator.name.casefold() not in disabled]
        return manager

    def validate(self, response: str, context: Mapping[str, Any] | None = None) -> PipelineResult:
        context = context or {}
        current = response
        results: list[ValidationResult] = []
        failed: list[str] = []
        for validator in self.validators:
            started = time.perf_counter()
            result = validator.validate(current, context)
            elapsed_ms = (time.perf_counter() - started) * 1000
            LOGGER.info(
                "response_validator validator=%s passed=%s score=%.3f execution_ms=%.3f issues=%s",
                validator.name,
                result.passed,
                result.score,
                elapsed_ms,
                result.issues,
                extra={"validator": validator.name, "passed": result.passed, "score": result.score, "execution_ms": elapsed_ms, "issues": result.issues},
            )
            results.append(result)
            if result.corrected_response is not None:
                current = result.corrected_response
            if not result.passed:
                failed.append(validator.name)
        return PipelineResult(current, not failed, results, failed)

    def process(
        self,
        response: str,
        context: Mapping[str, Any] | None = None,
        retry: Callable[[str], str] | None = None,
    ) -> str:
        first = self.validate(response, context)
        if first.passed:
            return first.response
        if retry is not None:
            feedback = self.feedback(first)
            second = self.validate(retry(feedback), context)
            if second.passed:
                return second.response
            if second.response and any(result.corrected_response is not None for result in second.results):
                final = self.validate(second.response, context)
                if final.passed:
                    return final.response
            if first.response and any(result.corrected_response is not None for result in first.results):
                repaired = self.validate(first.response, context)
                if repaired.passed:
                    return repaired.response
            raise ValidationError(second.issues)
        if first.response and any(result.corrected_response is not None for result in first.results):
            repaired = self.validate(first.response, context)
            if repaired.passed:
                return repaired.response
        raise ValidationError(first.issues)

    @staticmethod
    def feedback(result: PipelineResult) -> str:
        details = "\n".join(f"- {issue}" for issue in result.issues)
        return (
            "Your previous response failed response validation. Return a complete corrected answer. "
            "Do not discuss the validation process.\n" + details
        )


def validation_context(messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    user_text = next((item.get("content", "") for item in reversed(messages) if item.get("role") == "user"), "")
    system_text = "\n".join(item.get("content", "") for item in messages if item.get("role") == "system")
    expects_json = bool(re.search(r"\b(?:respond|return|output|answer|format(?:ted)?)\b[^.\n]{0,30}\bjson\b", user_text, re.IGNORECASE))
    expects_python = bool(re.search(r"\b(?:respond|return|output|answer)\b[^.\n]{0,40}\bpython(?: code)?\b", user_text, re.IGNORECASE))
    # Retrieved context asks the model to use citation labels, but omission should
    # not discard an otherwise useful answer. Enforce citations only when the
    # user explicitly requests them.
    requires_citations = bool(
        re.search(r"\b(?:cite|citations?|provide (?:your )?sources?)\b", user_text, re.IGNORECASE)
    )
    return {
        "messages": list(messages),
        "expects_json": expects_json,
        "expects_python": expects_python,
        "requires_citations": requires_citations,
    }
