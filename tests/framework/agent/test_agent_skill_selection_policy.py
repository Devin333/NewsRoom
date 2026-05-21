from __future__ import annotations

from pydantic import BaseModel

from framework.agent.skill_selection import SkillExposurePolicy, SkillSelectionPolicy


class FakeSkillMetadata(BaseModel):
    name: str
    description: str = "Skill description"
    category: str = "quality"
    tags: list[str] = []
    risk_level: str = "medium"
    status: str = "active"
    input_schema: str | None = None

    def canonical_name(self) -> str:
        return self.name.lower()

    def is_active(self) -> bool:
        return self.status == "active"


def test_low_and_medium_risk_are_visible_by_default() -> None:
    policy = SkillExposurePolicy()

    assert policy.allows(FakeSkillMetadata(name="low", risk_level="low")) is True
    assert policy.allows(FakeSkillMetadata(name="medium", risk_level="medium")) is True


def test_high_risk_is_hidden_by_default() -> None:
    policy = SkillExposurePolicy()

    assert policy.allows(FakeSkillMetadata(name="high", risk_level="high")) is False


def test_denied_skills_take_precedence() -> None:
    policy = SkillExposurePolicy(
        denied_skills=["entity-extraction"],
        allowed_skills=["entity-extraction"],
    )

    assert policy.allows(FakeSkillMetadata(name="entity-extraction")) is False


def test_allowed_skills_whitelist_is_enforced() -> None:
    policy = SkillExposurePolicy(allowed_skills=["evidence-checking"])

    assert policy.allows(FakeSkillMetadata(name="evidence-checking")) is True
    assert policy.allows(FakeSkillMetadata(name="entity-extraction")) is False


def test_keyword_score_uses_name_tags_category_and_description() -> None:
    skill = FakeSkillMetadata(
        name="entity-extraction",
        description="Extract normalized claims",
        category="extraction",
        tags=["entity"],
    )
    policy = SkillSelectionPolicy()

    assert policy.score_skill("extract entity claims", skill) == 7


def test_max_skills_limits_selected_results() -> None:
    skills = [
        FakeSkillMetadata(name="a-skill", description="extract"),
        FakeSkillMetadata(name="b-skill", description="extract"),
        FakeSkillMetadata(name="c-skill", description="extract"),
    ]
    policy = SkillSelectionPolicy(max_skills=2)

    assert [skill.name for skill in policy.select("extract", skills)] == [
        "a-skill",
        "b-skill",
    ]
