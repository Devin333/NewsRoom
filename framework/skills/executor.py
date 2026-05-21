"""Skill executor interfaces and simple adapters."""

from __future__ import annotations

import json
from typing import Protocol

from framework.skills.context import SkillRunContext
from framework.skills.io import SkillOutput
from framework.skills.package import SkillPackage
from framework.skills.prompt import SkillPromptBundle


class SkillExecutor(Protocol):
    def execute(
        self,
        package: SkillPackage,
        input_data: dict,
        prompt_bundle: SkillPromptBundle,
        context: SkillRunContext,
    ) -> SkillOutput:
        ...


class MockSkillExecutor:
    def __init__(self, outputs: dict[str, dict] | None = None):
        self.outputs = outputs or {}

    def execute(
        self,
        package: SkillPackage,
        input_data: dict,
        prompt_bundle: SkillPromptBundle,
        context: SkillRunContext,
    ) -> SkillOutput:
        _ = prompt_bundle, context
        if package.metadata.name in self.outputs:
            return SkillOutput.from_dict(dict(self.outputs[package.metadata.name]))
        return SkillOutput.from_dict({"echo": input_data})


class LLMSkillExecutor:
    def __init__(self, llm_client, response_parser=None):
        self.llm_client = llm_client
        self.response_parser = response_parser

    def execute(
        self,
        package: SkillPackage,
        input_data: dict,
        prompt_bundle: SkillPromptBundle,
        context: SkillRunContext,
    ) -> SkillOutput:
        messages = [
            {"role": "system", "content": prompt_bundle.combined_context()},
            {
                "role": "user",
                "content": json.dumps(
                    {"skill": package.metadata.name, "input": input_data, "context": context.model_dump(mode="json")},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        response = self.llm_client.generate(messages=messages)
        parsed = self.response_parser(response) if self.response_parser else _parse_response(response)
        if isinstance(parsed, SkillOutput):
            return parsed
        if isinstance(parsed, dict):
            return SkillOutput.from_dict(parsed)
        if isinstance(parsed, str):
            return SkillOutput.from_text(parsed)
        return SkillOutput.from_dict({"response": parsed})


def _parse_response(response):
    if isinstance(response, SkillOutput):
        return response
    if isinstance(response, dict):
        for key in ("structured_output", "output", "data"):
            value = response.get(key)
            if isinstance(value, dict):
                return value
        content = response.get("content") or response.get("text")
        if isinstance(content, str):
            return _parse_text(content)
        return response
    for attribute in ("structured_output", "output", "data"):
        value = getattr(response, attribute, None)
        if isinstance(value, dict):
            return value
    for attribute in ("content", "text"):
        value = getattr(response, attribute, None)
        if isinstance(value, str):
            return _parse_text(value)
    if isinstance(response, str):
        return _parse_text(response)
    return {"response": response}


def _parse_text(text: str):
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return payload if isinstance(payload, dict) else {"value": payload}
