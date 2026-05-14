import pytest

from core.framework.llm import (
    LLMStructuredOutputValidationError,
    validate_structured_output,
)


def test_validate_structured_output_accepts_nested_schema() -> None:
    schema = {
        "type": "object",
        "required": ["title", "sections"],
        "properties": {
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "sources"],
                    "properties": {
                        "title": {"type": "string"},
                        "sources": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": False,
                },
            },
            "decision": {"enum": ["pass", "revise"]},
        },
        "additionalProperties": False,
    }

    validate_structured_output(
        {
            "title": "Report",
            "sections": [{"title": "Summary", "sources": ["https://example.com"]}],
            "decision": "pass",
        },
        schema,
    )


def test_validate_structured_output_rejects_required_type_and_extra_fields() -> None:
    schema = {
        "type": "object",
        "required": ["title"],
        "properties": {"title": {"type": "string"}},
        "additionalProperties": False,
    }

    with pytest.raises(LLMStructuredOutputValidationError, match="missing required property"):
        validate_structured_output({}, schema)

    with pytest.raises(LLMStructuredOutputValidationError, match="expected string"):
        validate_structured_output({"title": 1}, schema)

    with pytest.raises(LLMStructuredOutputValidationError, match="unexpected properties"):
        validate_structured_output({"title": "Report", "extra": True}, schema)


def test_validate_structured_output_enforces_string_array_and_number_constraints() -> None:
    schema = {
        "type": "object",
        "required": ["slug", "confidence", "sources"],
        "properties": {
            "slug": {
                "type": "string",
                "minLength": 3,
                "maxLength": 12,
                "pattern": "^[a-z0-9-]+$",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^https://"},
            },
        },
    }

    validate_structured_output(
        {
            "slug": "ai-policy",
            "confidence": 0.7,
            "sources": ["https://example.com/a"],
        },
        schema,
    )

    with pytest.raises(LLMStructuredOutputValidationError, match="string does not match pattern"):
        validate_structured_output(
            {"slug": "AI Policy", "confidence": 0.7, "sources": ["https://example.com/a"]},
            schema,
        )

    with pytest.raises(LLMStructuredOutputValidationError, match="expected number <= 1.0"):
        validate_structured_output(
            {"slug": "ai-policy", "confidence": 1.2, "sources": ["https://example.com/a"]},
            schema,
        )

    with pytest.raises(LLMStructuredOutputValidationError, match="duplicate item at index 1"):
        validate_structured_output(
            {
                "slug": "ai-policy",
                "confidence": 0.7,
                "sources": ["https://example.com/a", "https://example.com/a"],
            },
            schema,
        )


def test_validate_structured_output_enforces_const_and_property_counts() -> None:
    schema = {
        "type": "object",
        "minProperties": 2,
        "maxProperties": 2,
        "properties": {
            "kind": {"const": "report"},
            "title": {"type": "string"},
        },
        "additionalProperties": False,
    }

    validate_structured_output({"kind": "report", "title": "Daily"}, schema)

    with pytest.raises(LLMStructuredOutputValidationError, match="value does not match const"):
        validate_structured_output({"kind": "draft", "title": "Daily"}, schema)

    with pytest.raises(LLMStructuredOutputValidationError, match="expected at least 2 properties"):
        validate_structured_output({"kind": "report"}, schema)


def test_validate_structured_output_accepts_pydantic_like_schema() -> None:
    class ReportSchema:
        @classmethod
        def model_json_schema(cls) -> dict:
            return {
                "type": "object",
                "required": ["title"],
                "properties": {"title": {"type": "string"}},
            }

    validate_structured_output({"title": "Daily"}, ReportSchema)

    with pytest.raises(LLMStructuredOutputValidationError, match="missing required property"):
        validate_structured_output({}, ReportSchema)
