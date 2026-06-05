from __future__ import annotations

import pytest
from pydantic import ValidationError

from framework.specs.skill_step import SkillStepSpec


def test_skill_step_spec_minimal_fields_are_valid() -> None:
    step = SkillStepSpec(id="extract_entities", skill="entity-extraction")

    assert step.id == "extract_entities"
    assert step.type == "skill"
    assert step.step_type() == "skill"
    assert step.validate_required_fields() == []


def test_skill_step_spec_missing_skill_fails() -> None:
    with pytest.raises(ValidationError):
        SkillStepSpec(id="extract_entities")


def test_skill_step_spec_input_defaults_to_empty_dict() -> None:
    step = SkillStepSpec(id="extract_entities", skill="entity-extraction")

    assert step.input == {}


def test_skill_step_spec_result_key() -> None:
    step = SkillStepSpec(id="extract_entities", skill="entity-extraction")

    assert step.result_key() == "extract_entities.result"


def test_skill_step_spec_output_buffer_key() -> None:
    step = SkillStepSpec(id="extract_entities", skill="entity-extraction")

    assert step.output_buffer_key() == "extract_entities.output"


def test_skill_step_spec_output_key_is_optional() -> None:
    step = SkillStepSpec(id="extract_entities", skill="entity-extraction")

    assert step.output_key is None
