from __future__ import annotations

from pathlib import Path

from interfaces.api import create_app
from interfaces.cli.news import build_parser
from interfaces.models import ApiMeta
from interfaces.services.mcp_service import MCPApplicationService
from newsroom_sdk import NewsRoomClient


def test_interface_acceptance_core_entrypoints_are_constructible() -> None:
    app = create_app(audit_emitter_factory=None)
    parser = build_parser()
    catalog = MCPApplicationService().catalog().to_dict()
    client = NewsRoomClient("http://localhost:8000")

    assert app.title == "NewsRoom API"
    assert parser.prog == "news"
    assert catalog["tools"]
    assert client.runs is not None
    assert client.reports is not None
    assert client.memory is not None
    assert client.mcp is not None


def test_interface_acceptance_openapi_and_api_response_schema_version() -> None:
    app = create_app(audit_emitter_factory=None)
    schema = app.openapi()
    meta = ApiMeta(request_id="acceptance")

    assert schema["openapi"]
    assert "/api/v2/graph-runs" in schema["paths"]
    assert "/api/v1/mcp/manifest" in schema["paths"]
    assert meta.schema_version == "1.0"


def test_interface_acceptance_web_console_files_exist() -> None:
    required_files = [
        "apps/web/package.json",
        "apps/web/src/app/layout.tsx",
        "apps/web/src/app/page.tsx",
        "apps/web/src/lib/api-client.ts",
        "apps/web/src/components/layout/AppShell.tsx",
    ]

    missing = [path for path in required_files if not Path(path).exists()]

    assert missing == []


def test_interface_acceptance_dev_commands_are_registered() -> None:
    import scripts.dev as dev

    parser = dev.build_parser()

    for argv in [
        ["test-interfaces"],
        ["test-api"],
        ["test-cli"],
        ["test-mcp"],
        ["test-sdk"],
        ["test-rag-eval-gate"],
        ["test-rag-live-e2e"],
        ["test-prd-daily"],
        ["web-check"],
        ["interface-smoke"],
    ]:
        args = parser.parse_args(argv)
        assert args.command == argv[0]
