from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from pydantic import BaseModel

from reviewkit import (
    LLMCapabilities,
    LLMClientError,
    LLMClientFailure,
    LLMRequestOptions,
    MockLLMClient,
    StructuredOutputMode,
)


class _Response(BaseModel):
    value: str = ""


@pytest.fixture
def preserved_environment() -> Iterator[None]:
    original = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_fake_client_is_injected_and_does_not_read_provider_environment(
    preserved_environment: None,
) -> None:
    os.environ["OPENAI_API_KEY"] = "must-not-be-read"
    os.environ["TEMIDA_LLM_MODEL"] = "must-not-be-selected"
    client = MockLLMClient(responses=[{"value": "ok"}])

    response = client.complete_json(
        [{"role": "user", "content": "typed input"}],
        _Response,
        options=LLMRequestOptions(max_output_tokens=32),
    )

    assert response == _Response(value="ok")
    assert client.calls[0].options == LLMRequestOptions(max_output_tokens=32)


def test_capabilities_are_explicit_not_derived_from_model_name() -> None:
    capabilities = LLMCapabilities(
        structured_output=StructuredOutputMode.JSON_SCHEMA,
        supports_tools=True,
        supports_reasoning=True,
    )
    client = MockLLMClient(capabilities=capabilities)
    assert client.capabilities is capabilities


def test_fake_client_propagates_redaction_safe_transport_error() -> None:
    error = LLMClientError(LLMClientFailure.TRANSPORT, reason_code="unavailable")
    client = MockLLMClient(responses=[error])
    with pytest.raises(LLMClientError) as caught:
        client.complete_json([{"role": "user", "content": "secret"}], _Response)
    assert caught.value.failure is LLMClientFailure.TRANSPORT
    assert "secret" not in str(caught.value)


def test_fake_client_propagates_timeout_error() -> None:
    client = MockLLMClient(
        responses=[LLMClientError(LLMClientFailure.TIMEOUT, reason_code="deadline")]
    )
    with pytest.raises(LLMClientError, match="timeout"):
        client.complete_json([], _Response)


def test_fake_client_fails_closed_on_schema_error() -> None:
    client = MockLLMClient(responses=[{"value": ["wrong"]}])
    with pytest.raises(Exception) as caught:
        client.complete_json([], _Response)
    assert "wrong" not in str(caught.value)


def test_request_options_reject_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="max_output_tokens"):
        LLMRequestOptions(max_output_tokens=0)
    with pytest.raises(ValueError, match="temperature"):
        LLMRequestOptions(temperature=-0.1)


def test_public_boundary_types_are_exported() -> None:
    import reviewkit

    for name in (
        "LLMCapabilities",
        "LLMClient",
        "LLMClientError",
        "LLMClientFailure",
        "LLMRequestOptions",
        "StructuredOutputMode",
    ):
        assert name in reviewkit.__all__
