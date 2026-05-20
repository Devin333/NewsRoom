from __future__ import annotations

import pytest

from framework.shared import RunId, StepId, TaskId, generate_id, stable_id
from framework.shared.errors import ValidationError


def test_generate_id_uses_normalized_prefix_and_uuid_hex() -> None:
    value = generate_id(" run id ")

    prefix, suffix = value.rsplit("_", 1)
    assert prefix == "run_id"
    assert len(suffix) == 32
    int(suffix, 16)


def test_stable_id_is_deterministic_for_canonical_payload() -> None:
    first = stable_id("topic", {"b": 2, "a": [1, 2]})
    second = stable_id("topic", {"a": [1, 2], "b": 2})

    assert first == second
    assert first.startswith("topic_")


def test_id_value_objects_validate_empty_values() -> None:
    with pytest.raises(ValidationError):
        RunId("")
    with pytest.raises(ValidationError):
        StepId(" ")
    with pytest.raises(ValidationError):
        TaskId("")


def test_run_id_new_and_string_value() -> None:
    run_id = RunId.new()

    assert str(run_id).startswith("run_")


def test_empty_prefix_is_rejected() -> None:
    with pytest.raises(ValidationError):
        generate_id(" ")
