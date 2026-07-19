from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import (
    ActorContext,
    MCPPromptGetRequest,
    MCPResourceReadRequest,
    MCPToolCallRequest,
)
from interfaces.services.mcp_service import (
    is_event_operator_resource_uri,
    resource_required_permission,
    tool_required_permission,
)


_MCP_ERROR_HTTP_CONTRACT = {
    "ArtifactPathError": (400, "invalid_artifact_path"),
    "ArtifactChecksumMismatchError": (409, "artifact_checksum_mismatch"),
    "ArtifactStoreMetadataError": (409, "artifact_metadata_corrupt"),
    "ArtifactStoreRequiredError": (500, "artifact_store_unavailable"),
    "ArtifactNotFoundError": (404, "artifact_not_found"),
    "MCPToolNotFound": (404, "mcp_tool_not_found"),
    "MCPResourceNotFound": (404, "mcp_resource_not_found"),
    "MCPPromptNotFound": (404, "mcp_prompt_not_found"),
    "ResearchActorAuthorizationError": (403, "forbidden"),
    "ResearchConfigurationError": (503, "research_configuration_invalid"),
    "ResearchQualityGateError": (422, "quality_gate_failed"),
    "ResearchRuntimeUnavailableError": (503, "research_runtime_unavailable"),
    "ResearchSourceError": (500, "research_run_failed"),
    "EventAuthorizationError": (403, "forbidden"),
    "EventOperationNotFoundError": (404, "event_operator_resource_not_found"),
    "EventOperationCapabilityUnavailableError": (
        503,
        "event_operator_capability_unavailable",
    ),
    "EventStoreUnavailableError": (503, "event_store_unavailable"),
    "EventContractError": (409, "event_operator_contract_conflict"),
    "EventRuntimeError": (500, "event_runtime_failed"),
    "ValueError": (400, "invalid_mcp_request"),
}

_MCP_SAFE_ERROR_MESSAGES = {
    "EventAuthorizationError": "event operator action is not authorized",
    "EventOperationNotFoundError": "event operator resource not found",
    "EventOperationCapabilityUnavailableError": "event operator capability is unavailable",
    "EventStoreUnavailableError": "event store is unavailable",
    "EventContractError": "event operator data conflicts with the durable event contract",
    "EventRuntimeError": "event runtime operation failed",
}


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/mcp/catalog")
    def mcp_catalog():
        return helpers.success(services.mcp_service_factory().catalog().to_dict())

    @router.get("/api/v1/mcp/capabilities")
    def mcp_capabilities():
        return helpers.success(services.mcp_service_factory().capability_manifest().to_dict())

    @router.get("/api/v1/mcp/manifest")
    def mcp_manifest():
        return helpers.success(services.mcp_service_factory().capability_manifest().to_dict())

    @router.post("/api/v1/mcp/tools/{tool_name}/call")
    def mcp_call_tool(tool_name: str, request: Request, payload: MCPToolCallRequest | None = None):
        actual_request = payload or MCPToolCallRequest()
        actor = getattr(request.state, "actor_context", None)
        required_permission = tool_required_permission(tool_name)
        if tool_name.startswith("news.event.") and not isinstance(actor, ActorContext):
            return _event_operator_authentication_error(helpers)
        if (
            required_permission
            and isinstance(actor, ActorContext)
            and not actor.has_permission(required_permission)
        ):
            return helpers.error(
                status_code=403,
                code="forbidden",
                message=f"missing required permission: {required_permission}",
                details={
                    "required_permission": required_permission,
                    "roles": actor.roles,
                    "tool_name": tool_name,
                },
                user_action_required=True,
            )
        service = _bind_actor(services.mcp_service_factory(), actor)
        result = service.call_tool(tool_name, actual_request.arguments)
        return _mcp_result_response(result, helpers=helpers, operation="call_tool")

    @router.post("/api/v1/mcp/resources/read")
    def mcp_read_resource(request: Request, payload: MCPResourceReadRequest):
        actor = getattr(request.state, "actor_context", None)
        required_permission = resource_required_permission(payload.uri)
        if is_event_operator_resource_uri(payload.uri) and not isinstance(
            actor, ActorContext
        ):
            return _event_operator_authentication_error(helpers)
        if (
            required_permission
            and isinstance(actor, ActorContext)
            and not actor.has_permission(required_permission)
        ):
            return helpers.error(
                status_code=403,
                code="forbidden",
                message=f"missing required permission: {required_permission}",
                details={
                    "required_permission": required_permission,
                    "roles": actor.roles,
                    "resource_uri": payload.uri,
                },
                user_action_required=True,
            )
        service = _bind_actor(services.mcp_service_factory(), actor)
        result = service.read_resource(payload.uri)
        return _mcp_result_response(result, helpers=helpers, operation="read_resource")

    @router.post("/api/v1/mcp/prompts/{prompt_name}/get")
    def mcp_get_prompt(prompt_name: str, request: MCPPromptGetRequest | None = None):
        actual_request = request or MCPPromptGetRequest()
        result = services.mcp_service_factory().get_prompt(prompt_name, actual_request.arguments)
        return _mcp_result_response(result, helpers=helpers, operation="get_prompt")

    return router


def _bind_actor(service: Any, actor: Any) -> Any:
    if not isinstance(actor, ActorContext):
        return service
    binder = getattr(service, "for_actor", None)
    return binder(actor) if callable(binder) else service


def _event_operator_authentication_error(helpers: ApiRouteHelpers) -> Any:
    return helpers.error(
        status_code=401,
        code="unauthorized",
        message="authenticated event operator required",
        user_action_required=True,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _mcp_result_response(
    result: Any,
    *,
    helpers: ApiRouteHelpers,
    operation: str,
) -> Any:
    payload = result.to_dict()
    if payload.get("success") is True:
        return helpers.success(payload)

    error_type = str(payload.get("error_type") or "MCPRequestFailed")
    status_code, code = _MCP_ERROR_HTTP_CONTRACT.get(
        error_type,
        (500, "mcp_request_failed"),
    )
    message = _MCP_SAFE_ERROR_MESSAGES.get(error_type)
    if message is None and error_type.startswith("Event") and error_type.endswith("Error"):
        message = "event operation failed"
    if message is None:
        message = str(payload.get("error_message") or f"MCP {operation} failed")
    return helpers.error(
        status_code=status_code,
        code=code,
        message=message,
        details={
            "error_type": error_type,
            "operation": operation,
        },
    )
