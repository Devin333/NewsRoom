"""Skill package manifests and catalog helpers."""

from __future__ import annotations

from pydantic import BaseModel, Field

from framework.skills.metadata import SkillMetadata


class SkillManifest(BaseModel):
    metadata: SkillMetadata
    package_hash: str | None = None
    files: list[str] = Field(default_factory=list)
    prompt_files: list[str] = Field(default_factory=list)
    schema_files: list[str] = Field(default_factory=list)
    reference_files: list[str] = Field(default_factory=list)
    example_files: list[str] = Field(default_factory=list)
    eval_files: list[str] = Field(default_factory=list)

    def to_public_dict(self) -> dict:
        """Return safe dict for logs/API."""
        return {
            "metadata": self.metadata.model_dump(mode="json"),
            "package_hash": self.package_hash,
            "files": list(self.files),
            "prompt_files": list(self.prompt_files),
            "schema_files": list(self.schema_files),
            "reference_files": list(self.reference_files),
            "example_files": list(self.example_files),
            "eval_files": list(self.eval_files),
        }


class SkillCatalog(BaseModel):
    skills: list[SkillMetadata] = Field(default_factory=list)

    def names(self) -> list[str]:
        """Sorted skill names."""
        return sorted(skill.name for skill in self.skills)

    def by_category(self) -> dict[str, list[str]]:
        """category -> skill names."""
        grouped: dict[str, list[str]] = {}
        for skill in self.skills:
            grouped.setdefault(skill.category.value, []).append(skill.name)
        return {category: sorted(names) for category, names in sorted(grouped.items())}

    def by_tag(self) -> dict[str, list[str]]:
        """tag -> skill names."""
        grouped: dict[str, list[str]] = {}
        for skill in self.skills:
            for tag in skill.tags:
                grouped.setdefault(tag, []).append(skill.name)
        return {tag: sorted(names) for tag, names in sorted(grouped.items())}
