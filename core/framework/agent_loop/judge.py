from __future__ import annotations

import re
from typing import Any

from core.framework.agent_loop.models import AgentAction, AgentSpec, JudgeDecision, JudgeVerdict


SECRET_PREFIX = "sk" + "-"
SECRET_PATTERNS = [
    re.compile(rf"{SECRET_PREFIX}[A-Za-z0-9_-]{{12,}}"),
    re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]+"),
]


class OutputJudge:
    def judge(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        called_tools: list[str],
    ) -> JudgeVerdict:
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

        policy_violations = [
            f"tool not allowed: {tool_name}"
            for tool_name in called_tools
            if tool_name not in agent.allowed_tools
        ]
        policy_violations.extend(self._source_violations(output, agent.allowed_sources))

        if self._contains_secret(output):
            return JudgeVerdict(
                decision=JudgeDecision.BLOCK,
                confidence=1.0,
                feedback="output contains secret-like content",
                policy_violations=["secret-like content detected"],
            )

        if missing_output_keys or policy_violations:
            feedback_parts = []
            if missing_output_keys:
                feedback_parts.append(f"missing output keys: {', '.join(missing_output_keys)}")
            if policy_violations:
                feedback_parts.append(f"policy violations: {', '.join(policy_violations)}")
            return JudgeVerdict(
                decision=JudgeDecision.RETRY,
                confidence=0.3,
                feedback="; ".join(feedback_parts),
                missing_output_keys=missing_output_keys,
                policy_violations=policy_violations,
            )

        return JudgeVerdict(
            decision=JudgeDecision.ACCEPT,
            confidence=1.0,
            feedback="accepted",
        )

    def _contains_secret(self, value: Any) -> bool:
        if isinstance(value, str):
            return any(pattern.search(value) for pattern in SECRET_PATTERNS)
        if isinstance(value, dict):
            return any(self._contains_secret(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_secret(item) for item in value)
        return False

    def _source_violations(self, output: Any, allowed_sources: list[str]) -> list[str]:
        if not allowed_sources:
            return []
        allowed = set(allowed_sources)
        violations: list[str] = []

        def inspect(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"source", "sources", "url", "urls"}:
                        inspect_source_value(item)
                    else:
                        inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        def inspect_source_value(value: Any) -> None:
            if isinstance(value, str) and value not in allowed:
                violations.append(f"source outside boundary: {value}")
            elif isinstance(value, list):
                for item in value:
                    inspect_source_value(item)

        inspect(output)
        return violations
