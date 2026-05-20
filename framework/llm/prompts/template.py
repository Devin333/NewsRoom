from __future__ import annotations

from dataclasses import dataclass, field
from string import Formatter
from typing import Any

from framework.llm.prompts.variables import PromptVariables


@dataclass(frozen=True)
class PromptTemplate:
    template: str
    required_variables: tuple[str, ...] = field(default_factory=tuple)

    def render(self, variables: PromptVariables | dict[str, Any]) -> str:
        values = variables.to_dict() if isinstance(variables, PromptVariables) else dict(variables)
        required = set(self.required_variables) or {
            field_name
            for _, field_name, _, _ in Formatter().parse(self.template)
            if field_name
        }
        missing = sorted(name for name in required if name not in values)
        if missing:
            raise KeyError(f"missing prompt variables: {', '.join(missing)}")
        return self.template.format(**values)
