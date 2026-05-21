from __future__ import annotations

import pytest
from pydantic import ValidationError

from framework.agent.skill_call import SkillCall


def test_minimal_skill_call_is_valid() -> None:
    call = SkillCall(skill_name="entity-extraction")

    assert call.type == "skill_call"
    assert call.skill_name == "entity-extraction"


def test_skill_call_arguments_default_to_empty_dict() -> None:
    call = SkillCall(skill_name="entity-extraction")

    assert call.arguments == {}


def test_skill_call_ensure_call_id_generates_skill_prefixed_id() -> None:
    call = SkillCall(skill_name="entity-extraction").ensure_call_id()

    assert call.call_id is not None
    assert call.call_id.startswith("skill_")
    assert len(call.call_id) == len("skill_") + 8


def test_empty_skill_name_fails_validation() -> None:
    with pytest.raises(ValidationError):
        SkillCall(skill_name="")
