from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class SkillExposurePolicy(BaseModel):
    expose_low_risk: bool = True
    expose_medium_risk: bool = True
    expose_high_risk: bool = False

    allowed_categories: list[str] = Field(default_factory=list)
    denied_skills: list[str] = Field(default_factory=list)
    allowed_skills: list[str] = Field(default_factory=list)

    def allows(self, metadata: Any) -> bool:
        """Return whether skill can be exposed/executed."""
        name = _skill_name(metadata)
        if not name:
            return False
        canonical = _normalize(name)
        denied = {_normalize(item) for item in self.denied_skills}
        if canonical in denied:
            return False
        allowed_skills = {_normalize(item) for item in self.allowed_skills}
        if allowed_skills and canonical not in allowed_skills:
            return False
        if not _is_active(metadata):
            return False
        allowed_categories = {_normalize(item) for item in self.allowed_categories}
        category = _normalize(_metadata_value(metadata, "category", ""))
        if allowed_categories and category not in allowed_categories:
            return False
        risk = _normalize(_metadata_value(metadata, "risk_level", "medium"))
        if risk == "high":
            return self.expose_high_risk
        if risk == "low":
            return self.expose_low_risk
        return self.expose_medium_risk


class SkillSelectionPolicy:
    def __init__(
        self,
        exposure_policy: SkillExposurePolicy | None = None,
        max_skills: int = 12,
    ) -> None:
        self.exposure_policy = exposure_policy or SkillExposurePolicy()
        self.max_skills = max(0, int(max_skills))

    def select(
        self,
        task: str,
        available_skills: list[Any],
        context: dict[str, Any] | None = None,
    ) -> list[Any]:
        """
        1. filter by exposure policy
        2. score each skill
        3. sort by score desc then name
        4. limit max_skills
        """
        del context
        visible = [
            skill for skill in available_skills if self.exposure_policy.allows(skill)
        ]
        ranked = sorted(
            visible,
            key=lambda skill: (-self.score_skill(task, skill), _skill_name(skill)),
        )
        return ranked[: self.max_skills]

    def score_skill(self, task: str, skill: Any) -> float:
        """
        +3 if name token matches task
        +2 for tag match
        +1 for category match
        +1 for description token match
        """
        task_tokens = _tokens(task)
        score = 0.0
        if _token_match(task_tokens, _tokens(_skill_name(skill))):
            score += 3
        tag_tokens = set()
        for tag in _metadata_list(skill, "tags"):
            tag_tokens.update(_tokens(str(tag)))
        if _token_match(task_tokens, tag_tokens):
            score += 2
        if _token_match(task_tokens, _tokens(_metadata_value(skill, "category", ""))):
            score += 1
        if _token_match(task_tokens, _tokens(_metadata_value(skill, "description", ""))):
            score += 1
        return score


class SkillPromptFormatter:
    def format_available_skills(self, skills: list[Any]) -> str:
        """Return compact Available Skills prompt section."""
        if not skills:
            return "Available Skills: none"
        lines = ["Available Skills:"]
        for skill in skills:
            lines.append(f"- {_skill_name(skill)}")
            description = _metadata_value(skill, "description", "")
            if description:
                lines.append(f"  description: {_compact_line(description)}")
            category = _metadata_value(skill, "category", "")
            if category:
                lines.append(f"  category: {category}")
            risk = _metadata_value(skill, "risk_level", "")
            if risk:
                lines.append(f"  risk: {risk}")
            input_schema = _metadata_value(skill, "input_schema", "")
            if input_schema:
                lines.append(f"  input_schema: {input_schema}")
        return "\n".join(lines)


def _skill_name(metadata: Any) -> str:
    canonical_name = getattr(metadata, "canonical_name", None)
    if callable(canonical_name):
        value = canonical_name()
    else:
        value = _metadata_value(metadata, "name", "")
    return str(value or "").strip()


def _metadata_value(metadata: Any, key: str, default: Any = None) -> Any:
    if isinstance(metadata, dict):
        value = metadata.get(key, default)
    else:
        value = getattr(metadata, key, default)
    if hasattr(value, "value"):
        value = value.value
    return value


def _metadata_list(metadata: Any, key: str) -> list[Any]:
    value = _metadata_value(metadata, key, [])
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _is_active(metadata: Any) -> bool:
    is_active = getattr(metadata, "is_active", None)
    if callable(is_active):
        return bool(is_active())
    status = _normalize(_metadata_value(metadata, "status", "active"))
    return status not in {"disabled", "inactive", "false", "0"}


def _normalize(value: Any) -> str:
    text = value.value if hasattr(value, "value") else value
    return str(text or "").strip().lower()


def _tokens(value: Any) -> set[str]:
    return {
        item
        for item in re.split(r"[^a-zA-Z0-9]+", str(value or "").lower())
        if item
    }


def _token_match(left: set[str], right: set[str]) -> bool:
    for left_token in left:
        for right_token in right:
            if left_token == right_token:
                return True
            if len(left_token) >= 4 and right_token.startswith(left_token):
                return True
            if len(right_token) >= 4 and left_token.startswith(right_token):
                return True
    return False


def _compact_line(value: Any, max_chars: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3]}..."
