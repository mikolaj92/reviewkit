"""LLM abstraction and deterministic mock implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from reviewkit.models import ReviewBoundError, ReviewFailureClass
from reviewkit.review_bounds import validate_review_payload


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

    When no scripted responses are provided, it returns an empty instance of the
    requested response schema. Scripted payloads that are not the declared object
    schema fail closed with :class:`ReviewBoundError` (list vs object, timeout
    markers). Partial reviews are never success.
    """

    def __init__(self, responses: Sequence[BaseModel | Mapping[str, Any] | object] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[LLMCall] = []

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        self.calls.append(LLMCall(messages=messages, schema=schema))
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
        if isinstance(response, ReviewBoundError):
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


__all__ = ["LLMCall", "LLMClient", "MockLLMClient"]
