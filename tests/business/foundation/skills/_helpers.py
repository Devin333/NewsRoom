from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = REPO_ROOT / "business" / "foundation" / "skills"

SKILL_NAMES = [
    "source-reliability",
    "entity-extraction",
    "event-deduplication",
    "evidence-checking",
    "trend-analysis",
    "report-writing",
]

REQUIRED_PACKAGE_FILES = [
    "SKILL.md",
    "prompts/main.md",
    "prompts/repair.md",
    "prompts/judge.md",
    "schemas/input.schema.json",
    "schemas/output.schema.json",
    "references/method.md",
    "references/quality_rules.md",
    "examples/case_001.input.json",
    "examples/case_001.expected.json",
    "examples/case_002.input.json",
    "examples/case_002.expected.json",
    "evals/README.md",
    "README.md",
]


@dataclass(frozen=True)
class LoadedSkill:
    metadata: Any
    root_path: str


@dataclass(frozen=True)
class FallbackMetadata:
    name: str
    version: str
    description: str
    category: str
    tags: list[str]
    input_schema: str
    output_schema: str
    allowed_tools: list[str]
    risk_level: str
    owner: str
    quality_gates: list[str]


class FallbackSkillPackageLoader:
    def load(self, skill_root: str | Path) -> LoadedSkill:
        root = Path(skill_root)
        return LoadedSkill(metadata=self.load_metadata(root), root_path=str(root))

    def load_metadata(self, skill_root: str | Path) -> FallbackMetadata:
        data = parse_skill_frontmatter(Path(skill_root) / "SKILL.md")
        return FallbackMetadata(
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            description=str(data.get("description", "")),
            category=str(data.get("category", "")),
            tags=[str(tag) for tag in data.get("tags", [])],
            input_schema=str(data.get("input_schema", "")),
            output_schema=str(data.get("output_schema", "")),
            allowed_tools=[str(tool) for tool in data.get("allowed_tools", [])],
            risk_level=str(data.get("risk_level", "")),
            owner=str(data.get("owner", "")),
            quality_gates=[str(gate) for gate in data.get("quality_gates", [])],
        )


def skill_paths() -> list[Path]:
    return [SKILL_ROOT / name for name in SKILL_NAMES]


def parse_skill_frontmatter(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise AssertionError(f"{path} is missing YAML frontmatter")
    _, frontmatter, _ = content.split("---", 2)
    loaded = yaml.safe_load(frontmatter)
    assert isinstance(loaded, dict), f"{path} frontmatter must parse to a mapping"
    return loaded


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_skill_package(skill_path: Path) -> LoadedSkill | Any:
    try:
        from framework.skills import SkillPackageLoader
    except ModuleNotFoundError as exc:
        if exc.name != "framework.skills":
            raise
        return FallbackSkillPackageLoader().load(skill_path)

    return SkillPackageLoader().load(skill_path)


def metadata_value(metadata: Any, field: str) -> Any:
    value = getattr(metadata, field)
    if isinstance(value, list):
        return [getattr(item, "value", item) for item in value]
    return getattr(value, "value", value)
