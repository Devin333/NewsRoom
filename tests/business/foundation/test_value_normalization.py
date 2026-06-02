from __future__ import annotations

from dataclasses import dataclass

from business.foundation.value_normalization import (
    field_value,
    float_value,
    list_value,
    string_list,
    to_plain_dict,
)


def test_field_value_reads_mapping_and_object_attributes() -> None:
    assert field_value({"topic": "AI policy"}, "topic") == "AI policy"
    assert field_value(_Payload(topic="memory"), "topic") == "memory"
    assert field_value({}, "missing", default="fallback") == "fallback"


def test_to_plain_dict_copies_mappings_and_to_dict_payloads() -> None:
    payload = {"nested": {"value": 1}}
    copied = to_plain_dict(payload)
    copied["nested"]["value"] = 2

    assert payload["nested"]["value"] == 1
    assert to_plain_dict(_DictPayload()) == {"nested": {"value": 1}}
    assert to_plain_dict(None) == {}


def test_list_string_and_float_normalization() -> None:
    assert list_value(None) == []
    assert list_value(("a", "b")) == ["a", "b"]
    assert list_value("single") == ["single"]
    assert string_list(["a", None, 2, ""]) == ["a", "2"]
    assert float_value("0.75", default=None) == 0.75
    assert float_value("bad", default=0.0) == 0.0


@dataclass(frozen=True)
class _Payload:
    topic: str


class _DictPayload:
    def to_dict(self) -> dict:
        return {"nested": {"value": 1}}
