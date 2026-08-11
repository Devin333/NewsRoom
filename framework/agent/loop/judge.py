from __future__ import annotations

import re
from typing import Any

from framework.llm.structured_output import (
    LLMStructuredOutputValidationError,
    compile_structured_output_contract,
    structured_output_response_fingerprint,
    validate_compiled_structured_output,
)
from framework.agent.loop.extensions import OutputValidator
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
        pre_output_validators: list[OutputValidator] | None = None,
        output_validators: list[OutputValidator] | None = None,
    ) -> None:
        self._pre_output_validators = list(pre_output_validators or [])
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

        pre_validator_results = [
            result
            for validator in self._pre_output_validators
            if (result := validator(
                agent=agent,
                action=action,
                called_tools=called_tools,
                inputs=inputs or {},
            )).has_errors
            or result.block
        ]
        pre_schema_errors: list[str] = []
        pre_validation_errors: list[str] = []
        pre_policy_violations: list[str] = []
        for result in pre_validator_results:
            missing_output_keys.extend(result.missing_output_keys)
            pre_schema_errors.extend(result.schema_errors)
            pre_validation_errors.extend(result.validation_errors)
            pre_policy_violations.extend(result.policy_violations)
        pre_blocking_results = [result for result in pre_validator_results if result.block]
        if pre_blocking_results:
            return JudgeVerdict(
                decision=JudgeDecision.BLOCK,
                confidence=1.0,
                feedback=pre_blocking_results[0].feedback or "output validation blocked",
                missing_output_keys=missing_output_keys,
                schema_errors=pre_schema_errors,
                validation_errors=pre_validation_errors,
                policy_violations=pre_policy_violations,
            )

        (
            managed_schema_errors,
            structured_output_diagnostics,
            structured_output_contract,
            response_fingerprint,
        ) = self._schema_validation(
            output,
            agent.output_schema,
            execution_metadata=action.metadata.get(
                "structured_output_validation"
            ),
        )
        schema_errors = [*pre_schema_errors, *managed_schema_errors]
        validation_errors: list[str] = list(pre_validation_errors)
        tool_policy = agent.resolved_tool_policy()
        policy_violations = list(pre_policy_violations)
        policy_violations.extend(
            f"tool not allowed: {tool_name}"
            for tool_name in called_tools
            if not tool_policy.allows(tool_name)
        )
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
                structured_output_diagnostics=structured_output_diagnostics,
                structured_output_contract=structured_output_contract,
                response_fingerprint=response_fingerprint,
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
                structured_output_diagnostics=structured_output_diagnostics,
                structured_output_contract=structured_output_contract,
                response_fingerprint=response_fingerprint,
            )

        return JudgeVerdict(
            decision=JudgeDecision.ACCEPT,
            confidence=1.0,
            feedback="accepted",
            structured_output_contract=structured_output_contract,
            response_fingerprint=response_fingerprint,
        )

    def _schema_validation(
        self,
        output: dict[str, Any],
        output_schema: dict[str, Any] | None,
        *,
        execution_metadata: Any = None,
    ) -> tuple[list[str], list[dict[str, Any]], dict[str, Any] | None, str | None]:
        if output_schema is None:
            return [], [], None, None
        contract = compile_structured_output_contract(
            output_schema,
            schema_name="agent_output",
        )
        fingerprint = structured_output_response_fingerprint(output)
        execution_identity = contract.to_dict()
        if (
            isinstance(execution_metadata, dict)
            and execution_metadata.get("validated") is True
            and execution_metadata.get("schema_digest") == contract.schema_digest
            and execution_metadata.get("response_fingerprint") == fingerprint
        ):
            for field in (
                "projection_digest",
                "projection_mode",
                "provider_capability_revision",
            ):
                value = execution_metadata.get(field)
                if isinstance(value, str) and value:
                    execution_identity[field] = value
        try:
            validate_compiled_structured_output(output, contract)
        except LLMStructuredOutputValidationError as exc:
            diagnostics = [item.to_dict() for item in exc.diagnostics]
            return (
                [item["message"] for item in diagnostics],
                diagnostics,
                execution_identity,
                fingerprint,
            )
        return [], [], execution_identity, fingerprint

    def _contains_secret(self, value: Any) -> bool:
        if isinstance(value, str):
            return any(pattern.search(value) for pattern in SECRET_PATTERNS)
        if isinstance(value, dict):
            return any(self._contains_secret(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_secret(item) for item in value)
        return False
