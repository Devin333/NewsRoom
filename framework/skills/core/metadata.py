"""Public skill metadata models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from framework.skills.core.errors import SkillMetadataError


class SkillRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SkillStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"


class SkillCategory(str, Enum):
    SOURCE = "source"
    EXTRACTION = "extraction"
    RELATION = "relation"
    ANALYSIS = "analysis"
    OUTPUT = "output"
    MEMORY = "memory"
    QUALITY = "quality"
    GOVERNANCE = "governance"
    OTHER = "other"


class SkillToolPermission(str, Enum):
    LLM = "llm"
    SCHEMA_VALIDATOR = "schema_validator"
    WEB_FETCH = "web_fetch"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    DATABASE_READ = "database_read"
    DATABASE_WRITE = "database_write"
    SHELL = "shell"
    NETWORK_POST = "network_post"


class SkillVersion(BaseModel):
    major: int = Field(ge=0)
    minor: int = Field(ge=0)
    patch: int = Field(ge=0)

    @classmethod
    def parse(cls, value: str) -> "SkillVersion":
        """Parse '1.2.3'. Raise SkillMetadataError if invalid."""
        raw = str(value or "").strip()
        parts = raw.split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise SkillMetadataError(f"invalid skill version: {value!r}")
        try:
            return cls(major=int(parts[0]), minor=int(parts[1]), patch=int(parts[2]))
        except ValidationError as exc:
            raise SkillMetadataError(f"invalid skill version: {value!r}") from exc

    def __str__(self) -> str:
        """Return semantic version string."""
        return f"{self.major}.{self.minor}.{self.patch}"


class SkillMetadata(BaseModel):
    name: str = Field(min_length=1)
    version: str = "1.0.0"
    description: str = Field(min_length=1, max_length=2048)
    category: SkillCategory = SkillCategory.OTHER
    tags: list[str] = Field(default_factory=list)

    path: str = Field(min_length=1)
    entry_file: str = "SKILL.md"

    input_schema: str | None = None
    output_schema: str | None = None

    allowed_tools: list[SkillToolPermission] = Field(default_factory=list)
    risk_level: SkillRiskLevel = SkillRiskLevel.MEDIUM
    status: SkillStatus = SkillStatus.ACTIVE

    owner: str = "unknown"
    quality_gates: list[str] = Field(default_factory=list)

    aliases: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)

    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("name", "description", "path", "entry_file", mode="before")
    @classmethod
    def _strip_required_strings(cls, value: Any) -> Any:
        if value is None:
            return value
        return str(value).strip()

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        SkillVersion.parse(value)
        return value

    @field_validator("tags", "quality_gates", "aliases", "dependencies", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]

    def canonical_name(self) -> str:
        """Lowercase normalized skill name."""
        return _normalize_key(self.name)

    def is_active(self) -> bool:
        """True when status == ACTIVE."""
        return self.status == SkillStatus.ACTIVE

    def allows_tool(self, permission: str | SkillToolPermission) -> bool:
        """Check allowed_tools."""
        try:
            expected = (
                permission
                if isinstance(permission, SkillToolPermission)
                else SkillToolPermission(str(permission).strip().lower())
            )
        except ValueError:
            return False
        return expected in self.allowed_tools

    def matches_tag(self, tag: str) -> bool:
        """Case-insensitive tag match."""
        expected = str(tag).strip().lower()
        return any(item.lower() == expected for item in self.tags)

    def matches_category(self, category: str | SkillCategory) -> bool:
        """Category match."""
        try:
            expected = category if isinstance(category, SkillCategory) else SkillCategory(str(category).strip().lower())
        except ValueError:
            return False
        return self.category == expected


class SkillCapability(BaseModel):
    skill_name: str
    version: str
    category: SkillCategory
    input_schema: str | None = None
    output_schema: str | None = None
    allowed_tools: list[SkillToolPermission] = Field(default_factory=list)
    risk_level: SkillRiskLevel = SkillRiskLevel.MEDIUM
    supports_batch: bool = False
    supports_streaming: bool = False
    supports_evaluation: bool = True
    supports_repair: bool = False


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower()
