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
