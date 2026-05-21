from __future__ import annotations

import json

import pytest

from framework.agent.loop import AgentActionParser, parse_skill_call
from framework.agent.skill_call import SkillCall, SkillCallParseError


def test_parse_json_skill_call_success() -> None:
    action = AgentActionParser().parse(
        json.dumps(
            {
                "type": "skill_call",
                "skill_name": "evidence-checking",
                "arguments": {"claims": [], "sources": []},
                "reason": "Need verification.",
            }
        )
    )

    assert isinstance(action, SkillCall)
    assert action.skill_name == "evidence-checking"
    assert action.arguments == {"claims": [], "sources": []}
    assert action.call_id is not None


def test_parse_fenced_json_skill_call_success() -> None:
    action = AgentActionParser().parse(
        """```json
{
  "type": "skill_call",
  "skill_name": "entity-extraction",
  "arguments": {
    "item": {"title": "Example"}
  }
}
```"""
    )

    assert isinstance(action, SkillCall)
    assert action.skill_name == "entity-extraction"
    assert action.arguments["item"]["title"] == "Example"


def test_parse_skill_call_rejects_non_dict_arguments() -> None:
    with pytest.raises(SkillCallParseError):
        parse_skill_call(
            {
                "type": "skill_call",
                "skill_name": "entity-extraction",
                "arguments": [],
            }
        )


def test_parse_skill_call_requires_skill_name() -> None:
    with pytest.raises(SkillCallParseError):
        parse_skill_call({"type": "skill_call", "arguments": {}})


def test_parse_skill_call_ignores_other_action_types() -> None:
    assert parse_skill_call({"action_type": "final", "content": "done"}) is None
