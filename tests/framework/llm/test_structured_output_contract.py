from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, model_validator

from framework.llm import (
    LLMProviderError,
    LLMRequest,
    LLMRetryPolicy,
    LLMStructuredOutputParseError,
    LLMStructuredOutputSchemaError,
    LLMStructuredOutputValidationError,
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
    StructuredOutputLimits,
    compile_structured_output_contract,
    decode_structured_output,
    validate_structured_output,
    validate_structured_output_result,
)
from framework.llm.context.openai import OpenAICompatibleRequestNormalizer


class _NestedValue(BaseModel):
    label: str


class _TypedOutput(BaseModel):
    nested: _NestedValue
    label_length: int

    @model_validator(mode="after")
    def label_length_matches(self) -> _TypedOutput:
        if self.label_length != len(self.nested.label):
            raise ValueError("label length mismatch")
        return self


def _config() -> OpenAICompatibleConfig:
    return OpenAICompatibleConfig(
        provider="test-provider",
        base_url="https://llm.example/v1",
        model="test-model",
        api_key_env="TEST_STRUCTURED_OUTPUT_KEY",
    )


def _response_body(content: str) -> bytes:
    return json.dumps(
        {
            "id": "response-1",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2},
        }
    ).encode("utf-8")


def _local_ref_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "$defs": {
            "score": {
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}},
                "additionalProperties": False,
            }
        },
        "required": ["score"],
        "properties": {"score": {"$ref": "#/$defs/score"}},
        "additionalProperties": False,
    }


def test_local_draft_contract_resolves_refs_and_json_numeric_semantics() -> None:
    contract = compile_structured_output_contract(_local_ref_schema())

    assert validate_structured_output({"score": {"value": 1.0}}, contract) == {
        "score": {"value": 1.0}
    }
    with pytest.raises(LLMStructuredOutputValidationError) as raised:
        validate_structured_output({"score": {"value": True}}, contract)

    assert raised.value.diagnostics[0].instance_path == ("score", "value")
    assert raised.value.diagnostics[0].validator == "type"
    assert raised.value.diagnostics[0].contract_digest == contract.schema_digest


def test_enum_const_and_unique_items_use_json_equality() -> None:
    schema = {
        "type": "object",
        "required": ["enum_value", "const_value", "items"],
        "properties": {
            "enum_value": {"enum": [1]},
            "const_value": {"const": 1},
            "items": {"type": "array", "uniqueItems": True},
        },
    }

    with pytest.raises(LLMStructuredOutputValidationError) as raised:
        validate_structured_output(
            {"enum_value": True, "const_value": True, "items": [1, 1.0]},
            schema,
        )

    validators = {diagnostic.validator for diagnostic in raised.value.diagnostics}
    assert validators == {"const", "enum", "uniqueItems"}


def test_combinations_and_additional_properties_schema_do_not_fail_open() -> None:
    schema = {
        "type": "object",
        "required": ["kind", "payload"],
        "properties": {
            "kind": {"enum": ["count", "label"]},
            "payload": {
                "oneOf": [
                    {"type": "integer"},
                    {"type": "string", "minLength": 3},
                ]
            },
        },
        "additionalProperties": {"type": "boolean"},
    }

    assert validate_structured_output(
        {"kind": "count", "payload": 3, "reviewed": True},
        schema,
    )["payload"] == 3
    with pytest.raises(LLMStructuredOutputValidationError):
        validate_structured_output(
            {"kind": "count", "payload": 1.5, "reviewed": "yes"},
            schema,
        )


def test_pydantic_source_retains_nested_and_model_validation() -> None:
    request = LLMRequest(messages=[], output_schema=_TypedOutput)
    cloned = request.clone(model="resolved-model")

    assert request.output_schema["$defs"]["_NestedValue"]["type"] == "object"
    assert cloned.structured_output_schema_source() is _TypedOutput
    assert validate_structured_output(
        {"nested": {"label": "abc"}, "label_length": 3},
        cloned.structured_output_schema_source(),
    ) == {"nested": {"label": "abc"}, "label_length": 3}

    with pytest.raises(LLMStructuredOutputValidationError) as raised:
        validate_structured_output(
            {"nested": {"label": "abc"}, "label_length": 2},
            request.structured_output_schema_source(),
        )
    assert raised.value.code == "structured_output_typed_validation_error"


def test_pydantic_source_survives_openai_request_normalization() -> None:
    request = LLMRequest(messages=[], output_schema=_TypedOutput)

    normalized = OpenAICompatibleRequestNormalizer().normalize(
        request,
        provider="test-provider",
        model="resolved-model",
    )

    assert normalized.request.structured_output_schema_source() is _TypedOutput
    assert normalized.payload["response_format"]["json_schema"]["schema"]["type"] == "object"


@pytest.mark.parametrize(
    ("schema", "expected_code"),
    [
        ({"type": "array"}, "structured_output_root_type_error"),
        (
            {"type": "object", "$ref": "https://example.test/schema.json"},
            "schema_reference_forbidden",
        ),
        ({"type": "object", "$ref": "#/$defs/missing"}, "schema_preflight_error"),
        ({"type": "object", "$ref": "#"}, "schema_reference_forbidden"),
        ({"type": "object", "x-unapproved": True}, "schema_preflight_error"),
        ({"type": "object", "required": "name"}, "schema_preflight_error"),
        (
            {"type": "object", "properties": {"name": {"pattern": "(?P<name>x)"}}},
            "schema_preflight_error",
        ),
    ],
)
def test_schema_preflight_fails_closed(schema: dict[str, Any], expected_code: str) -> None:
    with pytest.raises(LLMStructuredOutputSchemaError) as raised:
        compile_structured_output_contract(schema)

    assert raised.value.code == expected_code
    assert raised.value.diagnostics[0].message


def test_schema_preflight_enforces_resource_limits() -> None:
    limits = StructuredOutputLimits(max_schema_nodes=4)

    with pytest.raises(LLMStructuredOutputSchemaError) as raised:
        compile_structured_output_contract(_local_ref_schema(), limits=limits)

    assert raised.value.code == "structured_output_limit_exceeded"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ('{"value":NaN}', "structured_output_non_finite_number"),
        ('{"value":Infinity}', "structured_output_non_finite_number"),
        ('{"value":1e400}', "structured_output_non_finite_number"),
        ('{"value":1,"value":2}', "structured_output_duplicate_key"),
        ('["not-an-object"]', "structured_output_root_type_error"),
        ('{"value":', "structured_output_parse_error"),
    ],
)
def test_strict_decoder_rejects_non_json_or_ambiguous_objects(
    content: str,
    expected_code: str,
) -> None:
    with pytest.raises(LLMStructuredOutputParseError) as raised:
        decode_structured_output(content)

    assert raised.value.code == expected_code


def test_strict_decoder_enforces_response_limits() -> None:
    with pytest.raises(LLMStructuredOutputParseError) as byte_error:
        decode_structured_output('{"value":1}', limits=StructuredOutputLimits(max_response_bytes=5))
    assert byte_error.value.code == "structured_output_limit_exceeded"

    with pytest.raises(LLMStructuredOutputParseError) as depth_error:
        decode_structured_output(
            '{"outer":{"inner":1}}',
            limits=StructuredOutputLimits(max_instance_depth=1),
        )
    assert depth_error.value.code == "structured_output_limit_exceeded"


def test_validation_result_is_bounded_and_does_not_echo_instance_values() -> None:
    secret = "TOPSECRET-structured-value"
    schema = {
        "type": "object",
        "required": ["first", "second"],
        "properties": {
            "first": {"type": "integer"},
            "second": {"type": "integer"},
        },
    }

    result = validate_structured_output_result(
        {"first": secret, "second": secret},
        schema,
        limits=StructuredOutputLimits(max_diagnostics=1),
    )

    assert result.accepted is False
    assert len(result.diagnostics) == 1
    assert secret not in json.dumps(result.diagnostics[0].to_dict())


def test_client_preflight_rejects_schema_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_STRUCTURED_OUTPUT_KEY", "test-key")
    calls = 0

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return _response_body("{}")

    client = OpenAICompatibleClient(_config(), transport=transport)
    with pytest.raises(LLMProviderError) as raised:
        client.complete(LLMRequest(messages=[], output_schema={"type": "array"}))

    assert calls == 0
    assert raised.value.error_type == "structured_output_schema_error"
    assert raised.value.retryable is False
    assert raised.value.diagnostics[0]["code"] == "structured_output_root_type_error"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ('{"value":NaN}', "structured_output_non_finite_number"),
        ('{"value":1,"value":2}', "structured_output_duplicate_key"),
    ],
)
def test_client_strict_decode_failure_is_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected_code: str,
) -> None:
    monkeypatch.setenv("TEST_STRUCTURED_OUTPUT_KEY", "test-key")
    calls = 0

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return _response_body(content)

    client = OpenAICompatibleClient(
        _config(),
        transport=transport,
        retry_policy=LLMRetryPolicy(max_attempts=3),
    )
    with pytest.raises(LLMProviderError) as raised:
        client.complete(
            LLMRequest(
                messages=[],
                output_schema={"type": "object", "properties": {"value": {}}},
            )
        )

    assert calls == 1
    assert raised.value.error_type == "structured_output_parse_error"
    assert raised.value.retryable is False
    assert raised.value.diagnostics[0]["code"] == expected_code


def test_client_sends_canonical_schema_and_returns_typed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_STRUCTURED_OUTPUT_KEY", "test-key")
    payloads: list[dict[str, Any]] = []

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _response_body('{"nested":{"label":"abc"},"label_length":3}')

    client = OpenAICompatibleClient(_config(), transport=transport)
    response = client.complete(LLMRequest(messages=[], output_schema=_TypedOutput))

    provider_schema = payloads[0]["response_format"]["json_schema"]["schema"]
    assert provider_schema["type"] == "object"
    assert "$defs" in provider_schema
    assert response.structured_output == {
        "nested": {"label": "abc"},
        "label_length": 3,
    }
    metadata = response.metadata["structured_output_validation"]
    assert metadata["validated"] is True
    assert metadata["schema_digest"].startswith("sha256:")
    assert metadata["schema_dialect"] == "draft2020-12-local-v1"


def test_client_returns_bounded_typed_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_STRUCTURED_OUTPUT_KEY", "test-key")
    secret = "TOPSECRET-label"

    def transport(request, timeout):  # type: ignore[no-untyped-def]
        return _response_body(
            json.dumps({"nested": {"label": secret}, "label_length": 1})
        )

    client = OpenAICompatibleClient(_config(), transport=transport)
    with pytest.raises(LLMProviderError) as raised:
        client.complete(LLMRequest(messages=[], output_schema=_TypedOutput))

    assert raised.value.error_type == "structured_output_validation_error"
    assert raised.value.diagnostics[0]["code"] == "structured_output_typed_validation_error"
    assert secret not in json.dumps(raised.value.to_dict(redact=False))
