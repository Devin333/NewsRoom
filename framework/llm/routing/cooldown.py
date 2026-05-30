from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.llm.clients.openai_compatible import LLMProviderError


@dataclass(frozen=True)
class LLMCooldownPolicy:
    cooldown_on_rate_limit_seconds: int = 60
    cooldown_on_server_error_seconds: int = 30
    failure_count_threshold: int = 3

    def __post_init__(self) -> None:
        if self.cooldown_on_rate_limit_seconds < 0:
            raise ValueError("cooldown_on_rate_limit_seconds must be non-negative")
        if self.cooldown_on_server_error_seconds < 0:
            raise ValueError("cooldown_on_server_error_seconds must be non-negative")
        if self.failure_count_threshold < 1:
            raise ValueError("failure_count_threshold must be at least 1")

    def cooldown_seconds_for(self, error: LLMProviderError) -> int:
        if error.error_type in {"rate_limit", "rate_limited"} or error.status_code == 429:
            return self.cooldown_on_rate_limit_seconds
        if error.error_type in {
            "server_error",
            "provider_server_error",
            "transient_network",
            "temporary_provider_error",
            "timeout",
            "provider_timeout",
            "provider_connection_error",
        }:
            return self.cooldown_on_server_error_seconds
        if error.status_code is not None and 500 <= error.status_code <= 599:
            return self.cooldown_on_server_error_seconds
        return 0


@dataclass(frozen=True)
class LLMCooldownState:
    deployment_id: str
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_until": _datetime_to_json(self.cooldown_until),
        }


class InMemoryLLMCooldownTracker:
    def __init__(
        self,
        policy: LLMCooldownPolicy | None = None,
        *,
        now_fn: Any | None = None,
    ) -> None:
        self.policy = policy or LLMCooldownPolicy()
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._states: dict[str, LLMCooldownState] = {}

    def is_available(self, deployment_id: str) -> bool:
        return self.cooldown_until(deployment_id) is None

    def record_failure(
        self,
        deployment_id: str,
        error: LLMProviderError,
    ) -> LLMCooldownState:
        current = self._states.get(deployment_id) or LLMCooldownState(deployment_id)
        failures = current.consecutive_failures + 1
        cooldown_until = current.cooldown_until
        cooldown_seconds = self.policy.cooldown_seconds_for(error) if error.retryable else 0
        if cooldown_seconds and failures >= self.policy.failure_count_threshold:
            cooldown_until = self._now_fn() + timedelta(seconds=cooldown_seconds)
        state = LLMCooldownState(
            deployment_id=deployment_id,
            consecutive_failures=failures,
            cooldown_until=cooldown_until,
        )
        self._states[deployment_id] = state
        return state

    def record_success(self, deployment_id: str) -> None:
        self._states.pop(deployment_id, None)

    def cooldown_until(self, deployment_id: str, *, now: datetime | None = None) -> datetime | None:
        state = self._states.get(deployment_id)
        if state is None or state.cooldown_until is None:
            return None
        actual_now: datetime = now or self._now_fn()
        if _normalize_datetime(state.cooldown_until) <= _normalize_datetime(actual_now):
            self._states[deployment_id] = LLMCooldownState(
                deployment_id=deployment_id,
                consecutive_failures=state.consecutive_failures,
                cooldown_until=None,
            )
            return None
        return state.cooldown_until

    def state(self, deployment_id: str) -> LLMCooldownState | None:
        return self._states.get(deployment_id)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value).isoformat().replace("+00:00", "Z")
