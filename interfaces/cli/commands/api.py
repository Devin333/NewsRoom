from __future__ import annotations

import argparse
import json
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    api_parser = subparsers.add_parser("api", help="Run HTTP API server")
    api_subparsers = api_parser.add_subparsers(dest="api_command", required=True)

    serve_parser = api_subparsers.add_parser("serve", help="Serve the HTTP API")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port")
    serve_parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    serve_parser.add_argument(
        "--log-level",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        default="info",
        help="Uvicorn log level",
    )
    serve_parser.set_defaults(handler=serve_api)

    openapi_parser = api_subparsers.add_parser("openapi", help="Export HTTP API OpenAPI schema")
    openapi_parser.add_argument("--json", action="store_true", help="Print full OpenAPI JSON")
    openapi_parser.add_argument("--output", default=None, help="Write OpenAPI JSON to this path")
    openapi_parser.set_defaults(handler=export_openapi)


def serve_api(args: argparse.Namespace) -> int:
    from interfaces.api.server import run_api_server

    try:
        run_api_server(
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    return 0


def export_openapi(args: argparse.Namespace) -> int:
    from interfaces.api.openapi import export_openapi_schema, summarize_openapi_schema

    schema = export_openapi_schema()
    if args.output:
        Path(args.output).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json or not args.output:
        payload = schema if args.json else summarize_openapi_schema(schema)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


add_api_commands = register


__all__ = ["add_api_commands", "export_openapi", "register", "serve_api"]
