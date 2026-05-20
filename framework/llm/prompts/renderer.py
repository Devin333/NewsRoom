from __future__ import annotations

from typing import Any

from framework.llm.prompts.template import PromptTemplate
from framework.llm.prompts.variables import PromptVariables


class PromptRenderer:
    def render(self, template: PromptTemplate | str, variables: PromptVariables | dict[str, Any]) -> str:
        prompt_template = template if isinstance(template, PromptTemplate) else PromptTemplate(template)
        return prompt_template.render(variables)
