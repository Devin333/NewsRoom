"""Skill directory scanner."""

from __future__ import annotations

from pathlib import Path

from framework.skills.core.metadata import SkillMetadata
from framework.skills.package.loader import SkillPackage, SkillPackageLoader


class SkillScanner:
    def __init__(self, loader: SkillPackageLoader | None = None, ignore_hidden: bool = True):
        self.loader = loader or SkillPackageLoader()
        self.ignore_hidden = ignore_hidden

    def scan(self, root_dir: str | Path) -> list[SkillMetadata]:
        """Scan root_dir/<skill-name>/SKILL.md."""
        return [self.loader.load_metadata(path) for path in self.iter_skill_dirs(root_dir)]

    def scan_packages(self, root_dir: str | Path) -> list[SkillPackage]:
        """Scan and load full packages."""
        return [self.loader.load(path) for path in self.iter_skill_dirs(root_dir)]

    def iter_skill_dirs(self, root_dir: str | Path) -> list[Path]:
        """Sorted candidate dirs. Skip hidden, files, __pycache__."""
        root = Path(root_dir)
        if not root.is_dir():
            return []

        candidates: list[Path] = []
        for path in root.iterdir():
            if not path.is_dir():
                continue
            if path.name == "__pycache__":
                continue
            if self.ignore_hidden and path.name.startswith("."):
                continue
            if self.is_skill_dir(path):
                candidates.append(path)
        return sorted(candidates, key=lambda item: item.name.lower())

    def is_skill_dir(self, path: Path) -> bool:
        """True if path/SKILL.md exists."""
        return (path / self.loader.skill_file_name).is_file()
