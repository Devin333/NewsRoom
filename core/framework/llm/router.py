from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from core.framework.llm.capabilities import ModelCapabilities
from core.framework.llm.cost import LLMBudgetExceededError, LLMBudgetGuard, LLMBudgetPolicy, ModelPricing
from core.framework.llm.models import LLMClient, LLMRequest, LLMResponse
from core.framework.llm.openai_compatible import LLMProviderError
from core.framework.llm.redaction import redact_sensitive_values


@dataclass(frozen=True)
class ModelDeployment:
    deployment_id: str
    provider: str
    model: str
    client: LLMClient
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    pricing: ModelPricing | None = None
    enabled: bool = True
    cooldown_until: datetime | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelRoute:
    route_id: str
    primary_deployment_id: str
    fallback_deployment_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    budget_policy: LLMBudgetPolicy | None = None
    metadata: dict[str, Any] | None = None

    def deployment_chain(self) -> tuple[str, ...]:
        return (self.primary_deployment_id, *self.fallback_deployment_ids)


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
        if error.error_type == "rate_limited" or error.status_code == 429:
            return self.cooldown_on_rate_limit_seconds
        if error.error_type in {
            "provider_server_error",
            "temporary_provider_error",
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
        now = now or self._now_fn()
        if _normalize_datetime(state.cooldown_until) <= _normalize_datetime(now):
            self._states[deployment_id] = LLMCooldownState(
                deployment_id=deployment_id,
                consecutive_failures=state.consecutive_failures,
                cooldown_until=None,
            )
            return None
        return state.cooldown_until

    def state(self, deployment_id: str) -> LLMCooldownState | None:
        return self._states.get(deployment_id)


class LLMRouteError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        route_id: str,
        error_type: str,
        retryable: bool = False,
        attempted_deployments: Iterable[str] = (),
        errors: Iterable[dict[str, Any]] = (),
    ) -> None:
        super().__init__(message)
        self.route_id = route_id
        self.error_type = error_type
        self.retryable = retryable
        self.attempted_deployments = tuple(attempted_deployments)
        self.errors = tuple(dict(error) for error in errors)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": str(self),
            "route_id": self.route_id,
            "error_type": self.error_type,
            "retryable": self.retryable,
            "attempted_deployments": list(self.attempted_deployments),
            "errors": [dict(error) for error in self.errors],
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload


class LLMRouter:
    def __init__(
        self,
        *,
        routes: Iterable[ModelRoute],
        deployments: Iterable[ModelDeployment],
        cooldown_tracker: InMemoryLLMCooldownTracker | None = None,
        now_fn: Any | None = None,
    ) -> None:
        self._routes = {route.route_id: route for route in routes}
        self._deployments = {
            deployment.deployment_id: deployment
            for deployment in deployments
        }
        self._cooldown_tracker = cooldown_tracker
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def complete(self, route_id: str, request: LLMRequest) -> LLMResponse:
        route = self._route(route_id)
        attempted_deployments: list[str] = []
        errors: list[dict[str, Any]] = []
        deployment_chain = route.deployment_chain()

        for index, deployment_id in enumerate(deployment_chain):
            attempted_deployments.append(deployment_id)
            deployment = self._deployment(route.route_id, deployment_id, attempted_deployments, errors)
            if not deployment.enabled:
                raise LLMRouteError(
                    f"LLM route {route.route_id} deployment is disabled: {deployment_id}",
                    route_id=route.route_id,
                    error_type="deployment_disabled",
                    retryable=False,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                )
            cooldown_until = self._active_cooldown_until(deployment)
            if cooldown_until is not None:
                errors.append(
                    {
                        "deployment_id": deployment_id,
                        "error_type": "deployment_in_cooldown",
                        "cooldown_until": _datetime_to_json(cooldown_until),
                        "retryable": True,
                    }
                )
                has_fallback = index < len(deployment_chain) - 1
                if has_fallback:
                    continue
                raise LLMRouteError(
                    f"LLM route {route.route_id} deployment is in cooldown: {deployment_id}",
                    route_id=route.route_id,
                    error_type="deployment_in_cooldown",
                    retryable=True,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                )
            missing_capabilities = deployment.capabilities.missing(route.required_capabilities)
            if missing_capabilities:
                errors.append(
                    {
                        "deployment_id": deployment_id,
                        "error_type": "missing_required_capability",
                        "missing_capabilities": list(missing_capabilities),
                        "retryable": False,
                    }
                )
                raise LLMRouteError(
                    f"LLM route {route.route_id} deployment lacks required capabilities: {deployment_id}",
                    route_id=route.route_id,
                    error_type="missing_required_capability",
                    retryable=False,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                )

            try:
                response = deployment.client.complete(request)
            except LLMProviderError as exc:
                error_payload = _provider_error_payload(deployment_id, exc)
                cooldown_state = self._record_provider_failure(deployment_id, exc)
                if cooldown_state is not None:
                    error_payload["cooldown_state"] = cooldown_state.to_dict()
                errors.append(error_payload)
                has_fallback = index < len(deployment_chain) - 1
                if exc.retryable and has_fallback:
                    continue
                raise LLMRouteError(
                    f"LLM route {route.route_id} failed at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="provider_error",
                    retryable=exc.retryable,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                ) from exc
            except Exception as exc:
                errors.append(
                    {
                        "deployment_id": deployment_id,
                        "error_type": "client_error",
                        "message": str(exc),
                        "retryable": False,
                    }
                )
                raise LLMRouteError(
                    f"LLM route {route.route_id} client failed at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="client_error",
                    retryable=False,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                ) from exc

            if self._cooldown_tracker is not None:
                self._cooldown_tracker.record_success(deployment_id)
            try:
                budget_check = _check_budget(route, deployment, response)
            except LLMBudgetExceededError as exc:
                errors.append(
                    {
                        "deployment_id": deployment_id,
                        "error_type": "llm_budget_exceeded",
                        "retryable": False,
                        "budget_check": exc.check.to_dict(),
                    }
                )
                raise LLMRouteError(
                    f"LLM route {route.route_id} exceeded budget at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="llm_budget_exceeded",
                    retryable=False,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                ) from exc

            return _with_routing_metadata(
                response,
                route_id=route.route_id,
                deployment=deployment,
                attempted_deployments=attempted_deployments,
                fallback_used=index > 0,
                budget_check=budget_check,
            )

        raise LLMRouteError(
            f"LLM route {route.route_id} has no deployments",
            route_id=route.route_id,
            error_type="empty_route",
            retryable=False,
            attempted_deployments=attempted_deployments,
            errors=errors,
        )

    def _route(self, route_id: str) -> ModelRoute:
        route = self._routes.get(route_id)
        if route is None:
            raise LLMRouteError(
                f"LLM route not found: {route_id}",
                route_id=route_id,
                error_type="route_not_found",
                retryable=False,
            )
        return route

    def _deployment(
        self,
        route_id: str,
        deployment_id: str,
        attempted_deployments: list[str],
        errors: list[dict[str, Any]],
    ) -> ModelDeployment:
        deployment = self._deployments.get(deployment_id)
        if deployment is None:
            raise LLMRouteError(
                f"LLM deployment not found: {deployment_id}",
                route_id=route_id,
                error_type="deployment_not_found",
                retryable=False,
                attempted_deployments=attempted_deployments,
                errors=errors,
            )
        return deployment

    def _active_cooldown_until(self, deployment: ModelDeployment) -> datetime | None:
        now = self._now_fn()
        candidates: list[datetime] = []
        if deployment.cooldown_until is not None and (
            _normalize_datetime(deployment.cooldown_until) > _normalize_datetime(now)
        ):
            candidates.append(deployment.cooldown_until)
        if self._cooldown_tracker is not None:
            dynamic_until = self._cooldown_tracker.cooldown_until(
                deployment.deployment_id,
                now=now,
            )
            if dynamic_until is not None:
                candidates.append(dynamic_until)
        if not candidates:
            return None
        return max(candidates, key=_normalize_datetime)

    def _record_provider_failure(
        self,
        deployment_id: str,
        error: LLMProviderError,
    ) -> LLMCooldownState | None:
        if self._cooldown_tracker is None or not error.retryable:
            return None
        return self._cooldown_tracker.record_failure(deployment_id, error)


def _provider_error_payload(deployment_id: str, error: LLMProviderError) -> dict[str, Any]:
    payload = error.to_dict()
    payload["deployment_id"] = deployment_id
    return payload


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value).isoformat().replace("+00:00", "Z")


def _check_budget(
    route: ModelRoute,
    deployment: ModelDeployment,
    response: LLMResponse,
):
    if route.budget_policy is None:
        return None
    return LLMBudgetGuard(route.budget_policy).check_call(response.usage, deployment.pricing)


def _with_routing_metadata(
    response: LLMResponse,
    *,
    route_id: str,
    deployment: ModelDeployment,
    attempted_deployments: list[str],
    fallback_used: bool,
    budget_check,
) -> LLMResponse:
    metadata = dict(response.metadata)
    metadata.update(
        {
            "llm_route_id": route_id,
            "llm_deployment_id": deployment.deployment_id,
            "llm_provider": deployment.provider,
            "llm_model": deployment.model,
            "llm_capabilities": deployment.capabilities.to_dict(),
            "llm_fallback_used": fallback_used,
            "llm_attempted_deployments": list(attempted_deployments),
        }
    )
    if budget_check is not None:
        metadata["llm_estimated_cost_usd"] = budget_check.estimated_cost_usd
        metadata["llm_budget_check"] = budget_check.to_dict()
    return replace(response, metadata=metadata)
