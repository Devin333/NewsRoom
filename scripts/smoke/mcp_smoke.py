from __future__ import annotations

from interfaces.services.mcp_service import MCPApplicationService


def main() -> int:
    service = MCPApplicationService()
    catalog = service.catalog().to_dict()
    manifest = service.capability_manifest().to_dict()

    if not catalog["tools"]:
        print("mcp_smoke=failed reason=empty_tools")
        return 1
    if not catalog["resources"]:
        print("mcp_smoke=failed reason=empty_resources")
        return 1
    if not catalog["prompts"]:
        print("mcp_smoke=failed reason=empty_prompts")
        return 1
    if manifest["version"] != "1.0":
        print(f"mcp_smoke=failed reason=version value={manifest['version']}")
        return 1
    if manifest["capability_count"] != len(manifest["capabilities"]):
        print("mcp_smoke=failed reason=capability_count")
        return 1

    print("mcp_smoke=ok")
    print(f"tools={len(catalog['tools'])}")
    print(f"resources={len(catalog['resources'])}")
    print(f"prompts={len(catalog['prompts'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
