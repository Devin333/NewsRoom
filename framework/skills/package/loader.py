"""Local skill package loading."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from framework.skills.core.errors import SkillMetadataError, SkillPackageError
from framework.skills.core.manifest import SkillManifest
from framework.skills.core.metadata import SkillMetadata


class SkillPackage(BaseModel):
    metadata: SkillMetadata
    root_path: str
    skill_md_path: str

    prompt_paths: list[str] = Field(default_factory=list)
    schema_paths: list[str] = Field(default_factory=list)
    reference_paths: list[str] = Field(default_factory=list)
    example_paths: list[str] = Field(default_factory=list)
    eval_paths: list[str] = Field(default_factory=list)
    readme_path: str | None = None

    raw_skill_md: str = ""
    package_hash: str | None = None

    def root(self) -> Path:
        """Return root_path as Path."""
        return Path(self.root_path)

    def skill_md(self) -> Path:
        """Return skill_md_path as Path."""
        return Path(self.skill_md_path)

    def resolve_relative_path(self, relative_path: str) -> Path:
        """Resolve path relative to package root."""
        return self.root() / relative_path

    def has_input_schema(self) -> bool:
        """True if metadata.input_schema exists and file exists."""
        return bool(self.metadata.input_schema and self.resolve_relative_path(self.metadata.input_schema).is_file())

    def has_output_schema(self) -> bool:
        """True if metadata.output_schema exists and file exists."""
        return bool(self.metadata.output_schema and self.resolve_relative_path(self.metadata.output_schema).is_file())

    def manifest(self) -> SkillManifest:
        """Build SkillManifest."""
        files = sorted(
            {
                self.metadata.entry_file,
                *self.prompt_paths,
                *self.schema_paths,
                *self.reference_paths,
                *self.example_paths,
                *self.eval_paths,
                *([self.readme_path] if self.readme_path else []),
            }
        )
        return SkillManifest(
            metadata=self.metadata,
            package_hash=self.package_hash,
            files=files,
            prompt_files=list(self.prompt_paths),
            schema_files=list(self.schema_paths),
            reference_files=list(self.reference_paths),
            example_files=list(self.example_paths),
            eval_files=list(self.eval_paths),
        )


class SkillPackageLoader:
    def __init__(self, skill_file_name: str = "SKILL.md", max_skill_md_chars: int = 64000):
        self.skill_file_name = skill_file_name
        self.max_skill_md_chars = max_skill_md_chars

    def load(self, skill_root: str | Path) -> SkillPackage:
        """Load full package. Raise SkillPackageError / SkillMetadataError."""
        root = Path(skill_root)
        skill_md_path = root / self.skill_file_name
        raw_skill_md = self._read_skill_md(skill_md_path)
        metadata = self._metadata_from_content(raw_skill_md, root, skill_md_path)
        package = SkillPackage(
            metadata=metadata,
            root_path=str(root),
            skill_md_path=str(skill_md_path),
            prompt_paths=self.discover_files(root, "prompts"),
            schema_paths=self.discover_files(root, "schemas"),
            reference_paths=self.discover_files(root, "references"),
            example_paths=self.discover_files(root, "examples"),
            eval_paths=self.discover_files(root, "evals"),
            readme_path="README.md" if (root / "README.md").is_file() else None,
            raw_skill_md=raw_skill_md,
        )
        package.package_hash = self.compute_package_hash(package)
        return package

    def load_metadata(self, skill_root: str | Path) -> SkillMetadata:
        """Load only SKILL.md metadata."""
        root = Path(skill_root)
        skill_md_path = root / self.skill_file_name
        return self._metadata_from_content(self._read_skill_md(skill_md_path), root, skill_md_path)

    def parse_frontmatter(self, content: str, source_path: str) -> dict:
        """Parse YAML frontmatter with yaml.safe_load."""
        if not content.startswith("---"):
            raise SkillMetadataError(f"missing YAML frontmatter in {source_path}")

        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillMetadataError(f"missing YAML frontmatter in {source_path}")

        end_index: int | None = None
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_index = index
                break

        if end_index is None:
            raise SkillMetadataError(f"unterminated YAML frontmatter in {source_path}")

        raw_frontmatter = "\n".join(lines[1:end_index])
        try:
            parsed = yaml.safe_load(raw_frontmatter)
        except yaml.YAMLError as exc:
            raise SkillMetadataError(f"invalid YAML frontmatter in {source_path}: {exc}") from exc

        if not isinstance(parsed, dict):
            raise SkillMetadataError(f"frontmatter must be a mapping in {source_path}")
        return dict(parsed)

    def discover_files(self, root: Path, directory_name: str) -> list[str]:
        """Return sorted files under prompts/schemas/references/examples/evals."""
        directory = root / directory_name
        if not directory.is_dir():
            return []
        return sorted(
            path.relative_to(root).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        )

    def compute_package_hash(self, package: SkillPackage) -> str:
        """Stable hash from SKILL.md and package files."""
        digest = hashlib.sha256()
        for relative_path in package.manifest().files:
            path = package.resolve_relative_path(relative_path)
            if not path.is_file():
                continue
            digest.update(relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _read_skill_md(self, skill_md_path: Path) -> str:
        if not skill_md_path.is_file():
            raise SkillPackageError(f"missing {self.skill_file_name}: {skill_md_path}")
        content = skill_md_path.read_text(encoding="utf-8")
        if len(content) > self.max_skill_md_chars:
            raise SkillPackageError(f"{self.skill_file_name} exceeds {self.max_skill_md_chars} characters")
        return content

    def _metadata_from_content(self, content: str, root: Path, skill_md_path: Path) -> SkillMetadata:
        data = self.parse_frontmatter(content, str(skill_md_path))
        data["path"] = str(root)
        data["entry_file"] = self.skill_file_name
        self._require_frontmatter_fields(data, skill_md_path)
        try:
            return SkillMetadata(**data)
        except ValidationError as exc:
            raise SkillMetadataError(f"invalid skill metadata in {skill_md_path}: {exc}") from exc

    def _require_frontmatter_fields(self, data: dict[str, Any], skill_md_path: Path) -> None:
        missing = [
            field
            for field in ("name", "description")
            if data.get(field) is None or str(data.get(field)).strip() == ""
        ]
        if missing:
            joined = ", ".join(missing)
            raise SkillMetadataError(f"missing required metadata field(s) in {skill_md_path}: {joined}")
