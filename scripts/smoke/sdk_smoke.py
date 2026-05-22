from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk" / "python"))


def main() -> int:
    from newsroom_sdk import NewsRoomClient

    client = NewsRoomClient(
        "http://testserver",
        request_func=_request_func,
    )

    catalog = client.mcp.catalog()
    manifest = client.mcp.manifest()

    if not catalog.get("tools"):
        print("sdk_smoke=failed reason=empty_tools")
        return 1
    if manifest.get("version") != "1.0":
        print(f"sdk_smoke=failed reason=manifest_version value={manifest.get('version')}")
        return 1

    print("sdk_smoke=ok")
    return 0


def _request_func(method, path, *, headers, json=None, params=None, timeout=None):
    if method == "GET" and path == "/api/v1/mcp/catalog":
        data = {
            "tools": [{"name": "news.report.latest"}],
            "resources": [{"uri": "news://reports/latest"}],
            "prompts": [{"name": "news.run.diagnose"}],
        }
    elif method == "GET" and path == "/api/v1/mcp/manifest":
        data = {"version": "1.0", "capability_count": 0, "capabilities": []}
    else:
        data = {"ok": True}
    return {
        "success": True,
        "data": data,
        "error": None,
        "request_id": headers.get("X-Request-ID", "sdk-smoke"),
        "schema_version": "1.0",
    }


if __name__ == "__main__":
    raise SystemExit(main())
