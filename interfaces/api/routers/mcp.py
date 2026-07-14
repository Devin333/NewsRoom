from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ActorContext, MCPPromptGetRequest, MCPResourceReadRequest, MCPToolCallRequest
from interfaces.services.mcp_service import tool_required_permission


_MCP_ERROR_HTTP_CONTRACT = {
    "ArtifactPathError": (400, "invalid_artifact_path"),
    "ArtifactChecksumMismatchError": (409, "artifact_checksum_mismatch"),
    "ArtifactStoreMetadataError": (409, "artifact_metadata_corrupt"),
    "ArtifactStoreRequiredError": (500, "artifact_store_unavailable"),
    "ArtifactNotFoundError": (404, "artifact_not_found"),
    "MCPToolNotFound": (404, "mcp_tool_not_found"),
    "MCPResourceNotFound": (404, "mcp_resource_not_found"),
    "MCPPromptNotFound": (404, "mcp_prompt_not_found"),
    "ValueError": (400, "invalid_mcp_request"),
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
        if isinstance(actor, ActorContext):
            required_permission = tool_required_permission(tool_name)
            if required_permission and not actor.has_permission(required_permission):
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
        result = services.mcp_service_factory().call_tool(tool_name, actual_request.arguments)
        return _mcp_result_response(result, helpers=helpers, operation="call_tool")

    @router.post("/api/v1/mcp/resources/read")
    def mcp_read_resource(request: MCPResourceReadRequest):
        result = services.mcp_service_factory().read_resource(request.uri)
        return _mcp_result_response(result, helpers=helpers, operation="read_resource")

    @router.post("/api/v1/mcp/prompts/{prompt_name}/get")
    def mcp_get_prompt(prompt_name: str, request: MCPPromptGetRequest | None = None):
        actual_request = request or MCPPromptGetRequest()
        result = services.mcp_service_factory().get_prompt(prompt_name, actual_request.arguments)
        return _mcp_result_response(result, helpers=helpers, operation="get_prompt")

    return router


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
