"""Provider-blind LLM protocol and deterministic fake implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel

from reviewkit.models import ReviewBoundError, ReviewFailureClass
from reviewkit.review_bounds import validate_review_payload


class StructuredOutputMode(StrEnum):
    """Structured-output capability declared by the injected client."""

    PROMPT_JSON = "prompt_json"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


@dataclass(frozen=True)
class LLMCapabilities:
    """Explicit endpoint capabilities; never inferred from a model name."""

    structured_output: StructuredOutputMode = StructuredOutputMode.PROMPT_JSON
    supports_tools: bool = False
    supports_reasoning: bool = False


@dataclass(frozen=True)
class LLMRequestOptions:
    """Provider-neutral bounds for one completion request."""

    deadline_monotonic: float | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_input_tokens", "max_output_tokens"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.temperature is not None and self.temperature < 0:
            raise ValueError("temperature must be non-negative")


class LLMClientFailure(StrEnum):
    """Content-free error class exposed by an injected transport."""

    TRANSPORT = "transport"
    TIMEOUT = "timeout"
    RESPONSE_SCHEMA = "response_schema"


class LLMClientError(RuntimeError):
    """A redaction-safe client failure that never includes prompts or responses."""

    def __init__(self, failure: LLMClientFailure, *, reason_code: str = "") -> None:
        self.failure = failure
        self.reason_code = reason_code
        suffix = f" code={reason_code}" if reason_code else ""
        super().__init__(f"LLM client {failure.value} failure{suffix}")


class LLMClient(Protocol):
    """Inference dependency supplied by the ReviewKit host."""

    @property
    def capabilities(self) -> LLMCapabilities: ...

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        *,
        options: LLMRequestOptions | None = None,
    ) -> BaseModel: ...


@dataclass(frozen=True)
class LLMCall:
    messages: list[dict[str, str]]
    schema: type[BaseModel]
    options: LLMRequestOptions | None = None

    @property
    def content(self) -> str:
        return "\n".join(message["content"] for message in self.messages)


class MockLLMClient:
    """Scriptable provider-blind fake for tests and examples.

    When no scripted responses are provided, it returns an empty instance of the
    requested response schema. Exceptions and typed client errors can be scripted
    directly. Invalid payload shapes fail closed with :class:`ReviewBoundError`.
    """

    def __init__(
        self,
        responses: Sequence[BaseModel | Mapping[str, Any] | BaseException | object] | None = None,
        *,
        capabilities: LLMCapabilities | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self.calls: list[LLMCall] = []
        self._capabilities = capabilities or LLMCapabilities()

    @property
    def capabilities(self) -> LLMCapabilities:
        return self._capabilities

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        *,
        options: LLMRequestOptions | None = None,
    ) -> BaseModel:
        self.calls.append(LLMCall(messages=messages, schema=schema, options=options))
        node_id = _node_id_from_messages(messages)
        if not self._responses:
            return schema()

        response = self._responses.pop(0)
        if response is TimeoutError or response == "timeout":
            raise ReviewBoundError(
                failure_class=ReviewFailureClass.TIMEOUT,
                node_id=node_id,
                reason="provider timeout",
            )
        if isinstance(response, BaseException):
            raise response
        return validate_review_payload(response, schema, node_id=node_id)


def _node_id_from_messages(messages: list[dict[str, str]]) -> str:
    for message in messages:
        content = message.get("content", "")
        marker = '"node_id": "'
        start = content.find(marker)
        if start < 0:
            continue
        start += len(marker)
        end = content.find('"', start)
        if end > start:
            return content[start:end]
    return "unknown"


__all__ = [
    "LLMCall",
    "LLMCapabilities",
    "LLMClient",
    "LLMClientError",
    "LLMClientFailure",
    "LLMRequestOptions",
    "MockLLMClient",
    "StructuredOutputMode",
]
