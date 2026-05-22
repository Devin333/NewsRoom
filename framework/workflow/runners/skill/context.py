from __future__ import annotations

from typing import Any, Protocol

from framework.skills.core.context import SkillRunContext


class SkillRunnerProtocol(Protocol):
    def run(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        context: SkillRunContext | None = None,
    ) -> Any:
        ...


__all__ = [
    "SkillRunContext",
    "SkillRunnerProtocol",
]
