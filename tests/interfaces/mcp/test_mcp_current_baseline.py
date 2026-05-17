from __future__ import annotations

from interfaces.services.mcp_service import MCPApplicationService


def test_current_mcp_catalog_and_manifest_baseline() -> None:
    service = MCPApplicationService()

    catalog = service.catalog()
    manifest = service.capability_manifest()

    assert catalog.tools
    assert catalog.resources
    assert manifest.version == "1.0"
