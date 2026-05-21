"""In-memory skill registry."""

from __future__ import annotations

from pathlib import Path

from framework.skills.errors import SkillDuplicateError, SkillNotFoundError
from framework.skills.metadata import SkillCategory, SkillMetadata, SkillStatus, SkillToolPermission
from framework.skills.package import SkillPackage, SkillPackageLoader
from framework.skills.scanner import SkillScanner


class SkillRegistry:
    def __init__(
        self,
        scanner: SkillScanner | None = None,
        loader: SkillPackageLoader | None = None,
    ) -> None:
        self.loader = loader or SkillPackageLoader()
        self.scanner = scanner or SkillScanner(loader=self.loader)
        self._skills: dict[str, SkillMetadata] = {}
        self._aliases: dict[str, str] = {}
        self._packages: dict[str, SkillPackage] = {}

    def scan(self, root_dir: str | Path, load_packages: bool = False) -> list[SkillMetadata]:
        """Scan and register skills."""
        if load_packages:
            packages = self.scanner.scan_packages(root_dir)
            for package in packages:
                self.register_package(package)
            return sorted([package.metadata for package in packages], key=lambda item: item.name)

        metadata_items = self.scanner.scan(root_dir)
        for metadata in metadata_items:
            self.register(metadata)
        return sorted(metadata_items, key=lambda item: item.name)

    def register(self, metadata: SkillMetadata) -> None:
        """Register metadata. Duplicate name/alias raises SkillDuplicateError."""
        name_key = _normalize_key(metadata.name)
        pending_keys: set[str] = set()
        self._ensure_available(name_key, metadata.name, pending_keys)
        for alias in metadata.aliases:
            self._ensure_available(_normalize_key(alias), alias, pending_keys)

        self._skills[name_key] = metadata
        for alias in metadata.aliases:
            self._aliases[_normalize_key(alias)] = name_key

    def register_package(self, package: SkillPackage) -> None:
        """Register package and metadata."""
        name_key = _normalize_key(package.metadata.name)
        if name_key not in self._skills:
            self.register(package.metadata)
        else:
            self._skills[name_key] = package.metadata
        self._packages[name_key] = package

    def list_all(self, include_disabled: bool = False) -> list[SkillMetadata]:
        """Sorted skill metadata list."""
        values = list(self._skills.values())
        if not include_disabled:
            values = [skill for skill in values if skill.status != SkillStatus.DISABLED]
        return sorted(values, key=lambda item: item.name)

    def get(self, name: str) -> SkillMetadata | None:
        """Get by name or alias."""
        key = _normalize_key(name)
        canonical = self._aliases.get(key, key)
        return self._skills.get(canonical)

    def require(self, name: str) -> SkillMetadata:
        """Get or raise SkillNotFoundError."""
        metadata = self.get(name)
        if metadata is None:
            raise SkillNotFoundError(f"skill not found: {name}")
        return metadata

    def get_package(self, name: str) -> SkillPackage | None:
        """Return loaded package if available."""
        key = _normalize_key(name)
        canonical = self._aliases.get(key, key)
        return self._packages.get(canonical)

    def find_by_category(self, category: str | SkillCategory) -> list[SkillMetadata]:
        """Find active skills by category."""
        return sorted(
            [skill for skill in self._skills.values() if skill.is_active() and skill.matches_category(category)],
            key=lambda item: item.name,
        )

    def find_by_tag(self, tag: str) -> list[SkillMetadata]:
        """Find active skills by tag."""
        return sorted(
            [skill for skill in self._skills.values() if skill.is_active() and skill.matches_tag(tag)],
            key=lambda item: item.name,
        )

    def find_by_allowed_tool(self, tool: str | SkillToolPermission) -> list[SkillMetadata]:
        """Find skills that allow a tool."""
        return sorted(
            [skill for skill in self._skills.values() if skill.is_active() and skill.allows_tool(tool)],
            key=lambda item: item.name,
        )

    def describe(self) -> dict:
        """Return total, active, disabled, categories, names."""
        all_skills = self.list_all(include_disabled=True)
        active = [skill for skill in all_skills if skill.is_active()]
        disabled = [skill for skill in all_skills if skill.status == SkillStatus.DISABLED]
        categories: dict[str, list[str]] = {}
        for skill in active:
            categories.setdefault(skill.category.value, []).append(skill.name)
        return {
            "total": len(all_skills),
            "active": len(active),
            "disabled": len(disabled),
            "categories": {key: sorted(value) for key, value in sorted(categories.items())},
            "names": sorted(skill.name for skill in active),
        }

    def clear(self) -> None:
        """Clear registry."""
        self._skills.clear()
        self._aliases.clear()
        self._packages.clear()

    def _ensure_available(self, key: str, display_name: str, pending_keys: set[str]) -> None:
        if not key:
            raise SkillDuplicateError("empty skill registry key")
        if key in pending_keys:
            raise SkillDuplicateError(f"duplicate skill name or alias: {display_name}")
        if key in self._skills:
            raise SkillDuplicateError(f"duplicate skill name or alias: {display_name}")
        if key in self._aliases:
            raise SkillDuplicateError(f"duplicate skill alias: {display_name}")
        pending_keys.add(key)


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower()
