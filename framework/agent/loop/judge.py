from __future__ import annotations

import re
from typing import Any

from framework.agent.runtime.llm import (
    LLMStructuredOutputValidationError,
    validate_structured_output,
)
from framework.agent.loop.extensions import OutputValidationResult, OutputValidator
from framework.agent.models import AgentAction, AgentSpec, JudgeDecision, JudgeVerdict


SECRET_PREFIX = "sk" + "-"
SECRET_PATTERNS = [
    re.compile(rf"{SECRET_PREFIX}[A-Za-z0-9_-]{{12,}}"),
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]+"),
]


class OutputJudge:
    def __init__(
        self,
        *,
        output_validators: list[OutputValidator] | None = None,
    ) -> None:
        self._output_validators = list(output_validators or [])

    def judge(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        called_tools: list[str],
        inputs: dict[str, Any] | None = None,
    ) -> JudgeVerdict:
        if action.action_type == "delegate_to_subagent":
            child_agent_id = action.subagent_id or ""
            if not agent.allows_subagent(child_agent_id):
                return JudgeVerdict(
                    decision=JudgeDecision.BLOCK,
                    confidence=1.0,
                    feedback=f"subagent delegation is not allowed: {child_agent_id}",
                    policy_violations=["subagent delegation not allowed"],
                )
            return JudgeVerdict(
                decision=JudgeDecision.ESCALATE,
                confidence=1.0,
                feedback="subagent delegation accepted by policy but orchestration is deferred",
                validation_errors=[
                    (
                        "delegation handoff: "
                        f"parent_agent_id={agent.agent_id}; "
                        f"child_agent_id={child_agent_id}; "
                        f"handoff_reason={action.handoff_reason or 'subagent delegation requested'}"
                    )
                ],
            )

        if action.action_type != "final_output":
            return JudgeVerdict(
                decision=JudgeDecision.RETRY,
                confidence=0.0,
                feedback="expected final_output action",
                schema_errors=["expected final_output action"],
            )

        output = action.output or {}
        missing_output_keys = []
        if agent.output_key not in output:
            missing_output_keys.append(agent.output_key)

        schema_errors = self._schema_errors(output, agent.output_schema)
        validation_errors: list[str] = []
        tool_policy = agent.resolved_tool_policy()
        policy_violations = [
            f"tool not allowed: {tool_name}"
            for tool_name in called_tools
            if not tool_policy.allows(tool_name)
        ]
        validator_results = [
            result
            for validator in self._output_validators
            if (result := validator(
                agent=agent,
                action=action,
                called_tools=called_tools,
                inputs=inputs or {},
            )).has_errors
            or result.block
        ]
        for result in validator_results:
            missing_output_keys.extend(result.missing_output_keys)
            schema_errors.extend(result.schema_errors)
            validation_errors.extend(result.validation_errors)
            policy_violations.extend(result.policy_violations)

        if self._contains_secret(output):
            return JudgeVerdict(
                decision=JudgeDecision.BLOCK,
                confidence=1.0,
                feedback="output contains secret-like content",
                policy_violations=["secret-like content detected"],
            )

        blocking_results = [result for result in validator_results if result.block]
        if blocking_results:
            return JudgeVerdict(
                decision=JudgeDecision.BLOCK,
                confidence=1.0,
                feedback=blocking_results[0].feedback or "output validation blocked",
                missing_output_keys=missing_output_keys,
                schema_errors=schema_errors,
                validation_errors=validation_errors,
                policy_violations=policy_violations,
            )

        if missing_output_keys or schema_errors or validation_errors or policy_violations:
            feedback_parts = []
            if missing_output_keys:
                feedback_parts.append(f"missing output keys: {', '.join(missing_output_keys)}")
            if schema_errors:
                feedback_parts.append(f"schema errors: {', '.join(schema_errors)}")
            if validation_errors:
                feedback_parts.append(f"validation errors: {', '.join(validation_errors)}")
            if policy_violations:
                feedback_parts.append(f"policy violations: {', '.join(policy_violations)}")
            return JudgeVerdict(
                decision=JudgeDecision.RETRY,
                confidence=0.3,
                feedback="; ".join(feedback_parts),
                missing_output_keys=missing_output_keys,
                schema_errors=schema_errors,
                validation_errors=validation_errors,
                policy_violations=policy_violations,
            )

        return JudgeVerdict(
            decision=JudgeDecision.ACCEPT,
            confidence=1.0,
            feedback="accepted",
        )

    def _schema_errors(
        self,
        output: dict[str, Any],
        output_schema: dict[str, Any] | None,
    ) -> list[str]:
        if output_schema is None:
            return []
        try:
            validate_structured_output(output, output_schema)
        except LLMStructuredOutputValidationError as exc:
            return [str(exc)]
        return []

    def _contains_secret(self, value: Any) -> bool:
        if isinstance(value, str):
            return any(pattern.search(value) for pattern in SECRET_PATTERNS)
        if isinstance(value, dict):
            return any(self._contains_secret(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_secret(item) for item in value)
        return False
