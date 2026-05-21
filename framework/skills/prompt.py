"""Prompt bundle construction for skill execution."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from framework.skills.context import SkillRunContext
from framework.skills.package import SkillPackage


class SkillPromptBundle(BaseModel):
    skill_name: str
    version: str

    skill_md: str = ""
    main_prompt: str = ""
    repair_prompt: str | None = None
    judge_prompt: str | None = None

    references: dict[str, str] = Field(default_factory=dict)
    examples: list[dict] = Field(default_factory=list)

    def combined_context(self, include_examples: bool = True) -> str:
        """Combine skill_md, main_prompt, references, examples."""
        sections: list[str] = []
        if self.skill_md:
            sections.append("# SKILL.md\n" + self.skill_md)
        if self.main_prompt:
            sections.append("# Main Prompt\n" + self.main_prompt)
        if self.references:
            references = "\n\n".join(f"## {name}\n{content}" for name, content in self.references.items())
            sections.append("# References\n" + references)
        if include_examples and self.examples:
            sections.append("# Examples\n" + json.dumps(self.examples, ensure_ascii=False, indent=2, sort_keys=True))
        return "\n\n".join(sections)


class SkillPromptBuilder:
    def __init__(self, max_reference_chars: int = 32000, max_examples: int = 3):
        self.max_reference_chars = max_reference_chars
        self.max_examples = max_examples

    def build(self, package: SkillPackage, input_data: dict, context: SkillRunContext) -> SkillPromptBundle:
        _ = input_data, context
        return SkillPromptBundle(
            skill_name=package.metadata.name,
            version=package.metadata.version,
            skill_md=package.raw_skill_md,
            main_prompt=self.load_prompt_file(package, "main") or "",
            repair_prompt=self.load_prompt_file(package, "repair"),
            judge_prompt=self.load_prompt_file(package, "judge"),
            references=self.load_references(package),
            examples=self.load_examples(package),
        )

    def load_prompt_file(self, package: SkillPackage, name: str) -> str | None:
        """Load prompts/<name>.md."""
        path = package.resolve_relative_path(f"prompts/{name}.md")
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def load_references(self, package: SkillPackage) -> dict[str, str]:
        """Load references/*.md with truncation."""
        root = package.root() / "references"
        if not root.is_dir():
            return {}
        references: dict[str, str] = {}
        for path in sorted(root.glob("*.md"), key=lambda item: item.name):
            references[path.name] = path.read_text(encoding="utf-8")[: self.max_reference_chars]
        return references

    def load_examples(self, package: SkillPackage) -> list[dict]:
        """Load paired examples/case_x.input.json and case_x.expected.json."""
        root = package.root() / "examples"
        if not root.is_dir():
            return []
        examples: list[dict] = []
        for input_path in sorted(root.glob("*.input.json"), key=lambda item: item.name):
            case_id = input_path.name[: -len(".input.json")]
            expected_path = root / f"{case_id}.expected.json"
            if not expected_path.is_file():
                continue
            examples.append(
                {
                    "case_id": case_id,
                    "input": _load_json(input_path),
                    "expected": _load_json(expected_path),
                }
            )
            if len(examples) >= self.max_examples:
                break
        return examples


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {"value": payload}
