from __future__ import annotations

import re
from typing import Any

from framework.workflow.runners.skill.accessors import buffer_read


_TEMPLATE_REF_PATTERN = re.compile(r"^\s*\{\{\s*(?P<key>[^{}]+?)\s*\}\}\s*$")


def resolve_skill_input(value: Any, buffer: Any) -> Any:
    if isinstance(value, str):
        match = _TEMPLATE_REF_PATTERN.match(value)
        if match is not None:
            return buffer_read(buffer, match.group("key").strip())
        return value
    if isinstance(value, dict):
        return {str(key): resolve_skill_input(item, buffer) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_skill_input(item, buffer) for item in value]
    return value


__all__ = [
    "resolve_skill_input",
]
