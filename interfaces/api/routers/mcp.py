from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import MCPPromptGetRequest, MCPResourceReadRequest, MCPToolCallRequest


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
    def mcp_call_tool(tool_name: str, request: MCPToolCallRequest | None = None):
        actual_request = request or MCPToolCallRequest()
        result = services.mcp_service_factory().call_tool(tool_name, actual_request.arguments)
        return helpers.success(result.to_dict())

    @router.post("/api/v1/mcp/resources/read")
    def mcp_read_resource(request: MCPResourceReadRequest):
        result = services.mcp_service_factory().read_resource(request.uri)
        return helpers.success(result.to_dict())

    @router.post("/api/v1/mcp/prompts/{prompt_name}/get")
    def mcp_get_prompt(prompt_name: str, request: MCPPromptGetRequest | None = None):
        actual_request = request or MCPPromptGetRequest()
        result = services.mcp_service_factory().get_prompt(prompt_name, actual_request.arguments)
        return helpers.success(result.to_dict())

    return router
