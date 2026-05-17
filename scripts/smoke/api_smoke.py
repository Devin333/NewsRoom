from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app


def main() -> int:
    client = TestClient(create_app(audit_emitter_factory=None))

    health = client.get("/health", headers={"X-Request-ID": "smoke-api-health"})
    schema = client.get("/api/v1/mcp/catalog", headers={"X-Request-ID": "smoke-api-mcp"})

    if health.status_code != 200:
        print(f"api_smoke=failed path=/health status={health.status_code}")
        return 1
    if schema.status_code != 200:
        print(f"api_smoke=failed path=/api/v1/mcp/catalog status={schema.status_code}")
        return 1

    health_payload = health.json()
    catalog_payload = schema.json()
    if health_payload.get("schema_version") != "1.0":
        print("api_smoke=failed reason=health_schema_version")
        return 1
    if catalog_payload.get("schema_version") != "1.0":
        print("api_smoke=failed reason=mcp_schema_version")
        return 1
    if not catalog_payload.get("data", {}).get("tools"):
        print("api_smoke=failed reason=empty_mcp_tools")
        return 1

    print("api_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
