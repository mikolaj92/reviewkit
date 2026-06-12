"""LLM abstraction and deterministic mock implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


class LLMClient(Protocol):
    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel: ...


@dataclass(frozen=True)
class LLMCall:
    messages: list[dict[str, str]]
    schema: type[BaseModel]

    @property
    def content(self) -> str:
        return "\n".join(message["content"] for message in self.messages)


class MockLLMClient:
    """Scriptable LLM for tests and examples.

    When no scripted responses are provided, it returns an empty instance of the requested
    response schema.
    """

    def __init__(self, responses: Sequence[BaseModel | Mapping[str, Any]] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[LLMCall] = []

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        self.calls.append(LLMCall(messages=messages, schema=schema))
        if not self._responses:
            return schema()

        response = self._responses.pop(0)
        if isinstance(response, BaseModel):
            return schema.model_validate(response.model_dump(mode="json"))
        return schema.model_validate(response)
