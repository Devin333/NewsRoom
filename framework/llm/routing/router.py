from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Iterable

from framework.llm.budget import (
    GlobalBudgetExceededError,
    GlobalBudgetTracker,
    LLMBudgetExceededError,
    LLMBudgetGuard,
)
from framework.llm.clients.openai_compatible import LLMProviderError
from framework.llm.context import estimate_request_tokens
from framework.llm.models import LLMRequest, LLMResponse
from framework.llm.redaction import redact_sensitive_values
from framework.llm.routing.cooldown import InMemoryLLMCooldownTracker, LLMCooldownState
from framework.llm.routing.deployment import ModelDeployment
from framework.llm.routing.errors import LLMRouteError
from framework.llm.routing.events import LLMRouterEvent, LLMRouterEventSink
from framework.llm.routing.route import LLMRoutingPolicy, ModelRoute

class LLMRouter:
    def __init__(
        self,
        *,
        routes: Iterable[ModelRoute],
        deployments: Iterable[ModelDeployment],
        routing_policy: LLMRoutingPolicy | None = None,
        cooldown_tracker: InMemoryLLMCooldownTracker | None = None,
        global_budget_tracker: GlobalBudgetTracker | None = None,
        now_fn: Any | None = None,
        event_sink: LLMRouterEventSink | None = None,
    ) -> None:
        self._routes = {route.route_id: route for route in routes}
        self._deployments = {
            deployment.deployment_id: deployment
            for deployment in deployments
        }
        self._routing_policy = routing_policy
        self._cooldown_tracker = cooldown_tracker
        self._global_budget_tracker = global_budget_tracker
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._event_sink = event_sink

    def resolve_route_id(
        self,
        *,
        route_id: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
    ) -> str:
        resolved, trace = self._resolve_route_id_with_trace(
            route_id=route_id,
            agent_id=agent_id,
            task_type=task_type,
        )
        if not resolved:
            raise LLMRouteError(
                "LLM route could not be resolved",
                route_id=route_id or "",
                error_type="route_not_resolved",
                retryable=False,
                errors=[
                    {
                        "agent_id": agent_id,
                        "task_type": task_type,
                        "routing_policy_configured": self._routing_policy is not None,
                        "resolution_trace": trace,
                    }
                ],
            )
        return resolved

    def complete_for(
        self,
        request: LLMRequest,
        *,
        route_id: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        resolved, resolution_trace = self._resolve_route_id_with_trace(
            route_id=route_id,
            agent_id=agent_id,
            task_type=task_type,
        )
        if not resolved:
            raise LLMRouteError(
                "LLM route could not be resolved",
                route_id=route_id or "",
                error_type="route_not_resolved",
                retryable=False,
                errors=[
                    {
                        "agent_id": agent_id,
                        "task_type": task_type,
                        "routing_policy_configured": self._routing_policy is not None,
                        "resolution_trace": resolution_trace,
                    }
                ],
            )
        return self._complete(resolved, request, resolution_trace=resolution_trace)

    def complete(self, route_id: str, request: LLMRequest) -> LLMResponse:
        return self._complete(route_id, request, resolution_trace=())

    def _complete(
        self,
        route_id: str,
        request: LLMRequest,
        *,
        resolution_trace: Iterable[dict[str, Any]],
    ) -> LLMResponse:
        route = self._route(route_id)
        attempted_deployments: list[str] = []
        errors: list[dict[str, Any]] = []
        deployment_chain = route.deployment_chain()
        resolution_trace = tuple(dict(item) for item in resolution_trace)
        route_events: list[LLMRouterEvent] = []
        prompt_token_estimate = estimate_request_tokens(request)
        self._record_event(
            route_events,
            "llm_route_started",
            route.route_id,
            metadata={
                "deployment_chain": list(deployment_chain),
                "required_capabilities": list(route.required_capabilities),
                "resolution_trace": list(resolution_trace),
                "estimated_prompt_tokens": prompt_token_estimate,
            },
        )

        for index, deployment_id in enumerate(deployment_chain):
            attempted_deployments.append(deployment_id)
            deployment = self._deployment(route.route_id, deployment_id, attempted_deployments, errors)
            self._record_event(
                route_events,
                "llm_deployment_attempt_started",
                route.route_id,
                deployment=deployment,
                metadata={
                    "attempt_index": index + 1,
                    "fallback_attempt": index > 0,
                },
            )
            if not deployment.enabled:
                self._record_event(
                    route_events,
                    "llm_deployment_rejected",
                    route.route_id,
                    deployment=deployment,
                    metadata={"reason": "deployment_disabled", "retryable": False},
                )
                raise self._build_route_error(
                    f"LLM route {route.route_id} deployment is disabled: {deployment_id}",
                    route_id=route.route_id,
                    error_type="deployment_disabled",
                    retryable=False,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
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
                self._record_event(
                    route_events,
                    "llm_deployment_skipped",
                    route.route_id,
                    deployment=deployment,
                    metadata={
                        "reason": "deployment_in_cooldown",
                        "cooldown_until": _datetime_to_json(cooldown_until),
                        "retryable": True,
                    },
                    aliases=("deployment_skipped_cooldown",),
                )
                if has_fallback:
                    self._record_fallback_event(
                        route_events,
                        route_id=route.route_id,
                        from_deployment=deployment,
                        to_deployment_id=deployment_chain[index + 1],
                        reason="deployment_in_cooldown",
                        errors=errors,
                    )
                    continue
                raise self._build_route_error(
                    f"LLM route {route.route_id} deployment is in cooldown: {deployment_id}",
                    route_id=route.route_id,
                    error_type="deployment_in_cooldown",
                    retryable=True,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
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
                self._record_event(
                    route_events,
                    "llm_deployment_rejected",
                    route.route_id,
                    deployment=deployment,
                    metadata={
                        "reason": "missing_required_capability",
                        "missing_capabilities": list(missing_capabilities),
                        "retryable": False,
                    },
                )
                raise self._build_route_error(
                    f"LLM route {route.route_id} deployment lacks required capabilities: {deployment_id}",
                    route_id=route.route_id,
                    error_type="missing_required_capability",
                    retryable=False,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
                )

            try:
                preflight_budget_check = self._check_global_budget_before_call(
                    estimated_prompt_tokens=prompt_token_estimate,
                )
            except GlobalBudgetExceededError as exc:
                errors.append(
                    {
                        "deployment_id": deployment_id,
                        "error_type": "global_budget_exceeded",
                        "retryable": False,
                        "global_budget_check": exc.check.to_dict(),
                    }
                )
                self._record_event(
                    route_events,
                    "llm_global_budget_exceeded",
                    route.route_id,
                    deployment=deployment,
                    metadata={
                        "phase": "preflight",
                        "global_budget_check": exc.check.to_dict(),
                        "retryable": False,
                    },
                )
                raise self._build_route_error(
                    f"LLM route {route.route_id} exceeded global budget before deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="global_budget_exceeded",
                    retryable=False,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
                ) from exc

            try:
                response = deployment.client.complete(request)
            except LLMProviderError as exc:
                error_payload = _provider_error_payload(deployment_id, exc)
                cooldown_state = self._record_provider_failure(deployment_id, exc)
                if cooldown_state is not None:
                    error_payload["cooldown_state"] = cooldown_state.to_dict()
                errors.append(error_payload)
                has_fallback = index < len(deployment_chain) - 1
                self._record_event(
                    route_events,
                    "llm_deployment_attempt_failed",
                    route.route_id,
                    deployment=deployment,
                    metadata={
                        "error_type": exc.error_type,
                        "error_category": _canonical_error_category(exc.error_type),
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                        "attempts": exc.attempts,
                    },
                    aliases=("route_attempt_failed",),
                )
                if exc.retryable and has_fallback:
                    self._record_fallback_event(
                        route_events,
                        route_id=route.route_id,
                        from_deployment=deployment,
                        to_deployment_id=deployment_chain[index + 1],
                        reason=exc.error_type,
                        errors=errors,
                    )
                    continue
                raise self._build_route_error(
                    f"LLM route {route.route_id} failed at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="provider_error",
                    retryable=exc.retryable,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
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
                self._record_event(
                    route_events,
                    "llm_deployment_attempt_failed",
                    route.route_id,
                    deployment=deployment,
                    metadata={
                        "error_type": "client_error",
                        "message": str(exc),
                        "retryable": False,
                    },
                    aliases=("route_attempt_failed",),
                )
                raise self._build_route_error(
                    f"LLM route {route.route_id} client failed at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="client_error",
                    retryable=False,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
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
                self._record_event(
                    route_events,
                    "llm_budget_exceeded",
                    route.route_id,
                    deployment=deployment,
                    metadata={"budget_check": exc.check.to_dict(), "retryable": False},
                )
                raise self._build_route_error(
                    f"LLM route {route.route_id} exceeded budget at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="llm_budget_exceeded",
                    retryable=False,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
                ) from exc
            try:
                global_budget_check = self._record_global_budget_call(
                    response,
                    deployment=deployment,
                    budget_check=budget_check,
                    prompt_token_estimate=prompt_token_estimate,
                )
            except GlobalBudgetExceededError as exc:
                errors.append(
                    {
                        "deployment_id": deployment_id,
                        "error_type": "global_budget_exceeded",
                        "retryable": False,
                        "global_budget_check": exc.check.to_dict(),
                    }
                )
                self._record_event(
                    route_events,
                    "llm_global_budget_exceeded",
                    route.route_id,
                    deployment=deployment,
                    metadata={
                        "phase": "post_call",
                        "global_budget_check": exc.check.to_dict(),
                        "retryable": False,
                    },
                )
                raise self._build_route_error(
                    f"LLM route {route.route_id} exceeded global budget at deployment {deployment_id}",
                    route_id=route.route_id,
                    error_type="global_budget_exceeded",
                    retryable=False,
                    request=request,
                    attempted_deployments=attempted_deployments,
                    errors=errors,
                    events=route_events,
                    resolution_trace=resolution_trace,
                ) from exc
            self._record_event(
                route_events,
                "llm_deployment_attempt_succeeded",
                route.route_id,
                deployment=deployment,
                metadata={
                    "attempt_index": index + 1,
                    "usage": response.usage.to_dict(),
                    "preflight_global_budget_check": (
                        preflight_budget_check.to_dict()
                        if preflight_budget_check is not None
                        else None
                    ),
                    "budget_check": budget_check.to_dict() if budget_check is not None else None,
                    "global_budget_check": (
                        global_budget_check.to_dict() if global_budget_check is not None else None
                    ),
                },
            )
            self._record_event(
                route_events,
                "llm_route_completed",
                route.route_id,
                deployment=deployment,
                metadata={
                    "attempted_deployments": list(attempted_deployments),
                    "fallback_used": index > 0,
                },
            )

            return _with_routing_metadata(
                response,
                request=request,
                route_id=route.route_id,
                deployment=deployment,
                attempted_deployments=attempted_deployments,
                fallback_used=index > 0,
                budget_check=budget_check,
                global_budget_check=global_budget_check,
                events=route_events,
                errors=errors,
                resolution_trace=resolution_trace,
            )

        raise self._build_route_error(
            f"LLM route {route.route_id} has no deployments",
            route_id=route.route_id,
            error_type="empty_route",
            retryable=False,
            request=request,
            attempted_deployments=attempted_deployments,
            errors=errors,
            events=route_events,
            resolution_trace=resolution_trace,
        )

    def _resolve_route_id_with_trace(
        self,
        *,
        route_id: str | None = None,
        agent_id: str | None = None,
        task_type: str | None = None,
    ) -> tuple[str | None, tuple[dict[str, Any], ...]]:
        if self._routing_policy is None:
            explicit_route = _optional_text(route_id)
            return explicit_route, (
                {
                    "source": "explicit_route",
                    "matched": explicit_route is not None,
                    "route_id": explicit_route,
                    "routing_policy_configured": False,
                },
            )
        return self._routing_policy.resolve_with_trace(
            route_id=route_id,
            agent_id=agent_id,
            task_type=task_type,
        )

    def _record_event(
        self,
        events: list[LLMRouterEvent],
        event_type: str,
        route_id: str,
        *,
        deployment: ModelDeployment | None = None,
        deployment_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        aliases: Iterable[str] = (),
    ) -> LLMRouterEvent:
        event = LLMRouterEvent(
            event_type=event_type,
            route_id=route_id,
            deployment_id=deployment.deployment_id if deployment is not None else deployment_id,
            provider=deployment.provider if deployment is not None else None,
            model=deployment.model if deployment is not None else None,
            metadata=redact_sensitive_values(
                {
                    **dict(metadata or {}),
                    "event_aliases": list(aliases),
                    "event_name": _event_name_alias(event_type),
                }
            ),
            occurred_at=self._now_fn(),
        )
        events.append(event)
        if self._event_sink is not None:
            self._event_sink(event)
        return event

    def _record_fallback_event(
        self,
        events: list[LLMRouterEvent],
        *,
        route_id: str,
        from_deployment: ModelDeployment,
        to_deployment_id: str,
        reason: str,
        errors: list[dict[str, Any]],
    ) -> LLMRouterEvent:
        to_deployment = self._deployments.get(to_deployment_id)
        return self._record_event(
            events,
            "llm_fallback_selected",
            route_id,
            deployment=to_deployment,
            deployment_id=to_deployment_id,
            metadata={
                "from_deployment_id": from_deployment.deployment_id,
                "from_provider": from_deployment.provider,
                "from_model": from_deployment.model,
                "to_deployment_id": to_deployment_id,
                "to_provider": to_deployment.provider if to_deployment is not None else None,
                "to_model": to_deployment.model if to_deployment is not None else None,
                "reason": reason,
                "error_count": len(errors),
                "errors": [dict(error) for error in errors],
            },
            aliases=("fallback_selected",),
        )

    def _build_route_error(
        self,
        message: str,
        *,
        route_id: str,
        error_type: str,
        retryable: bool,
        request: LLMRequest,
        attempted_deployments: list[str],
        errors: list[dict[str, Any]],
        events: list[LLMRouterEvent],
        resolution_trace: Iterable[dict[str, Any]],
    ) -> LLMRouteError:
        self._record_event(
            events,
            "llm_route_failed",
            route_id,
            metadata={
                "error_type": error_type,
                "retryable": retryable,
                "attempted_deployments": list(attempted_deployments),
                "error_count": len(errors),
            },
        )
        event_payloads = _event_payloads(events)
        manifest = _build_route_manifest(
            route_id=route_id,
            status="failed",
            request=request,
            response=None,
            selected_deployment=None,
            attempted_deployments=attempted_deployments,
            fallback_used=_fallback_count(events) > 0,
            budget_check=None,
            events=event_payloads,
            errors=errors,
            resolution_trace=resolution_trace,
            error={
                "message": message,
                "error_type": error_type,
                "retryable": retryable,
            },
            global_budget_check=_last_global_budget_check(errors),
        )
        return LLMRouteError(
            message,
            route_id=route_id,
            error_type=error_type,
            retryable=retryable,
            attempted_deployments=attempted_deployments,
            errors=errors,
            events=event_payloads,
            manifest=manifest,
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

    def _check_global_budget_before_call(self, *, estimated_prompt_tokens: int):
        if self._global_budget_tracker is None:
            return None
        return self._global_budget_tracker.reserve_llm_call(
            estimated_prompt_tokens=estimated_prompt_tokens,
        )

    def _record_global_budget_call(
        self,
        response: LLMResponse,
        *,
        deployment: ModelDeployment,
        budget_check,
        prompt_token_estimate: int,
    ):
        if self._global_budget_tracker is None:
            return None
        estimated_cost_usd = (
            budget_check.estimated_cost_usd if budget_check is not None else None
        )
        return self._global_budget_tracker.record_llm_call(
            response.usage,
            deployment.pricing,
            estimated_cost_usd=estimated_cost_usd,
            replace_reserved_prompt_tokens=prompt_token_estimate,
            count_request=False,
        )


def _provider_error_payload(deployment_id: str, error: LLMProviderError) -> dict[str, Any]:
    payload = error.to_dict()
    payload["deployment_id"] = deployment_id
    payload["model"] = payload.get("model")
    payload["provider"] = payload.get("provider")
    payload["error_category"] = _canonical_error_category(str(payload.get("error_type") or ""))
    return payload


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    request: LLMRequest,
    route_id: str,
    deployment: ModelDeployment,
    attempted_deployments: list[str],
    fallback_used: bool,
    budget_check,
    global_budget_check,
    events: Iterable[LLMRouterEvent],
    errors: Iterable[dict[str, Any]],
    resolution_trace: Iterable[dict[str, Any]],
) -> LLMResponse:
    metadata = dict(response.metadata)
    event_payloads = _event_payloads(events)
    manifest = _build_route_manifest(
        route_id=route_id,
        status="succeeded",
        request=request,
        response=response,
        selected_deployment=deployment,
        attempted_deployments=attempted_deployments,
        fallback_used=fallback_used,
        budget_check=budget_check,
        global_budget_check=global_budget_check,
        events=event_payloads,
        errors=errors,
        resolution_trace=resolution_trace,
        error=None,
    )
    metrics = dict(manifest["metrics"])
    metadata.update(
        {
            "llm_route_id": route_id,
            "llm_deployment_id": deployment.deployment_id,
            "llm_provider": deployment.provider,
            "llm_model": deployment.model,
            "llm_capabilities": deployment.capabilities.to_dict(),
            "llm_fallback_used": fallback_used,
            "llm_attempted_deployments": list(attempted_deployments),
            "llm_fallback_count": metrics["fallback_count"],
            "llm_router_event_count": metrics["event_count"],
            "llm_provider_resolution_trace": [dict(item) for item in resolution_trace],
            "llm_router_events": event_payloads,
            "llm_route_manifest": manifest,
        }
    )
    if budget_check is not None:
        metadata["llm_estimated_cost_usd"] = budget_check.estimated_cost_usd
        metadata["llm_budget_check"] = budget_check.to_dict()
    if global_budget_check is not None:
        metadata["llm_global_budget_check"] = global_budget_check.to_dict()
        metadata["llm_global_budget_usage"] = global_budget_check.usage.to_dict()
    return replace(response, metadata=metadata)


def _event_payloads(events: Iterable[LLMRouterEvent | dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for event in events:
        if isinstance(event, LLMRouterEvent):
            payloads.append(event.to_dict())
        else:
            payloads.append(redact_sensitive_values(dict(event)))
    return payloads


def _build_route_manifest(
    *,
    route_id: str,
    status: str,
    request: LLMRequest,
    response: LLMResponse | None,
    selected_deployment: ModelDeployment | None,
    attempted_deployments: Iterable[str],
    fallback_used: bool,
    budget_check,
    events: Iterable[dict[str, Any]],
    errors: Iterable[dict[str, Any]],
    resolution_trace: Iterable[dict[str, Any]],
    error: dict[str, Any] | None,
    global_budget_check=None,
) -> dict[str, Any]:
    event_payloads = [dict(event) for event in events]
    errors_payload = [redact_sensitive_values(dict(item)) for item in errors]
    attempted_deployment_list = list(attempted_deployments)
    metrics = _route_metrics(event_payloads, attempted_deployment_list)
    manifest: dict[str, Any] = {
        "schema_version": "newsroom.llm_route_manifest.v1",
        "status": status,
        "route_id": route_id,
        "selected_deployment_id": (
            selected_deployment.deployment_id if selected_deployment is not None else None
        ),
        "selected_provider": selected_deployment.provider if selected_deployment is not None else None,
        "selected_model": selected_deployment.model if selected_deployment is not None else None,
        "attempted_deployments": attempted_deployment_list,
        "fallback_used": fallback_used,
        "fallback_count": metrics["fallback_count"],
        "provider_resolution_trace": [redact_sensitive_values(dict(item)) for item in resolution_trace],
        "events": event_payloads,
        "errors": errors_payload,
        "metrics": metrics,
        "redacted_request": request.to_dict(redact=True),
    }
    if response is not None:
        manifest["redacted_response"] = response.to_dict(redact=True)
    if budget_check is not None:
        manifest["budget_check"] = budget_check.to_dict()
    if global_budget_check is not None:
        if hasattr(global_budget_check, "to_dict"):
            manifest["global_budget_check"] = global_budget_check.to_dict()
            manifest["global_budget_usage"] = global_budget_check.usage.to_dict()
        elif isinstance(global_budget_check, dict):
            manifest["global_budget_check"] = dict(global_budget_check)
            usage = global_budget_check.get("usage")
            if isinstance(usage, dict):
                manifest["global_budget_usage"] = dict(usage)
    if error is not None:
        manifest["error"] = redact_sensitive_values(dict(error))
    return redact_sensitive_values(manifest)


def _route_metrics(
    events: Iterable[dict[str, Any]],
    attempted_deployments: Iterable[str],
) -> dict[str, Any]:
    event_list = [dict(event) for event in events]
    return {
        "attempt_count": len(list(attempted_deployments)),
        "event_count": len(event_list),
        "fallback_count": sum(
            1 for event in event_list if event.get("event_type") == "llm_fallback_selected"
        ),
        "provider_error_count": sum(
            1
            for event in event_list
            if event.get("event_type") == "llm_deployment_attempt_failed"
            and (event.get("metadata") or {}).get("error_type") != "client_error"
        ),
        "cooldown_skip_count": sum(
            1
            for event in event_list
            if event.get("event_type") == "llm_deployment_skipped"
            and (event.get("metadata") or {}).get("reason") == "deployment_in_cooldown"
        ),
    }


def _fallback_count(events: Iterable[LLMRouterEvent]) -> int:
    return sum(1 for event in events if event.event_type == "llm_fallback_selected")


def _event_name_alias(event_type: str) -> str:
    aliases = {
        "llm_deployment_attempt_failed": "route_attempt_failed",
        "llm_fallback_selected": "fallback_selected",
        "llm_deployment_skipped": "deployment_skipped_cooldown",
    }
    return aliases.get(event_type, event_type.removeprefix("llm_"))


def _canonical_error_category(error_type: str) -> str:
    aliases = {
        "rate_limited": "rate_limit",
        "provider_timeout": "timeout",
        "provider_connection_error": "transient_network",
        "temporary_provider_error": "transient_network",
        "provider_server_error": "server_error",
        "invalid_api_key": "auth_error",
        "invalid_request_schema": "invalid_request",
        "context_length_exceeded": "context_length",
        "invalid_model": "unsupported_model",
        "provider_response_shape_invalid": "schema_error",
        "provider_stream_chunk_invalid": "schema_error",
        "tool_call_parse_error": "schema_error",
        "stream_tool_call_parse_error": "schema_error",
        "structured_output_parse_error": "schema_error",
        "structured_output_validation_error": "schema_error",
    }
    return aliases.get(error_type, error_type)


def _last_global_budget_check(errors: Iterable[dict[str, Any]]):
    for error in reversed([dict(item) for item in errors]):
        check = error.get("global_budget_check")
        if check is not None:
            return check
    return None

