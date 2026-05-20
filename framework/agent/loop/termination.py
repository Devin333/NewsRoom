from __future__ import annotations

from typing import Any

from framework.agent.models import AgentLoopPolicy, AgentLoopStopReason


class TerminationController:
    def should_stop(
        self,
        state: Any,
        policy: AgentLoopPolicy,
    ) -> tuple[bool, AgentLoopStopReason | None]:
        if self._final_action_reached(state):
            return True, AgentLoopStopReason.FINAL_ANSWER
        if self._max_iterations_reached(state, policy):
            return True, AgentLoopStopReason.MAX_ITERATIONS
        if self._stalled(state):
            return True, AgentLoopStopReason.STALLED
        return False, None

    def _max_iterations_reached(self, state: Any, policy: AgentLoopPolicy) -> bool:
        return int(getattr(state, "iteration", 0) or 0) >= policy.max_iterations

    def _final_action_reached(self, state: Any) -> bool:
        action = getattr(state, "last_action", None)
        is_final = getattr(action, "is_final", None)
        return bool(is_final()) if callable(is_final) else False

    def _stalled(self, state: Any) -> bool:
        return bool(getattr(state, "stalled", False))
