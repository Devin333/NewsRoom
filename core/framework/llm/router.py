from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from core.framework.llm.capabilities import ModelCapabilities
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
    enabled: bool = True
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelRoute:
    route_id: str
    primary_deployment_id: str
    fallback_deployment_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def deployment_chain(self) -> tuple[str, ...]:
        return (self.primary_deployment_id, *self.fallback_deployment_ids)


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
    ) -> None:
        self._routes = {route.route_id: route for route in routes}
        self._deployments = {
            deployment.deployment_id: deployment
            for deployment in deployments
        }

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
                errors.append(_provider_error_payload(deployment_id, exc))
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

            return _with_routing_metadata(
                response,
                route_id=route.route_id,
                deployment=deployment,
                attempted_deployments=attempted_deployments,
                fallback_used=index > 0,
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


def _provider_error_payload(deployment_id: str, error: LLMProviderError) -> dict[str, Any]:
    payload = error.to_dict()
    payload["deployment_id"] = deployment_id
    return payload


def _with_routing_metadata(
    response: LLMResponse,
    *,
    route_id: str,
    deployment: ModelDeployment,
    attempted_deployments: list[str],
    fallback_used: bool,
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
    return replace(response, metadata=metadata)
