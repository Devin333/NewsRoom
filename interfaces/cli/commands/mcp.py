from __future__ import annotations

import argparse
import json

from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.mcp_service import MCPApplicationService


def register(subparsers: argparse._SubParsersAction) -> None:
    mcp_parser = subparsers.add_parser("mcp", help="Inspect inbound MCP catalog and tools")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    catalog_parser = mcp_subparsers.add_parser("catalog", help="Show MCP tools/resources/prompts")
    catalog_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    catalog_parser.set_defaults(handler=mcp_catalog)

    capabilities_parser = mcp_subparsers.add_parser(
        "capabilities",
        help="Show MCP capability summary",
    )
    capabilities_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    capabilities_parser.set_defaults(handler=mcp_capabilities)

    manifest_parser = mcp_subparsers.add_parser(
        "manifest",
        help="Show MCP capability manifest",
    )
    manifest_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    manifest_parser.set_defaults(handler=mcp_capabilities)

    call_parser = mcp_subparsers.add_parser("call", help="Call an MCP tool locally")
    call_parser.add_argument("tool_name", help="MCP tool name")
    call_parser.add_argument("--args-json", default="{}", help="Tool arguments as a JSON object")
    call_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    call_parser.set_defaults(handler=mcp_call)

    read_resource_parser = mcp_subparsers.add_parser("read-resource", help="Read an MCP resource locally")
    read_resource_parser.add_argument("uri", help="MCP resource URI")
    read_resource_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    read_resource_parser.set_defaults(handler=mcp_read_resource)

    get_prompt_parser = mcp_subparsers.add_parser("get-prompt", help="Get an MCP prompt locally")
    get_prompt_parser.add_argument("prompt_name", help="MCP prompt name")
    get_prompt_parser.add_argument("--args-json", default="{}", help="Prompt arguments as a JSON object")
    get_prompt_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    get_prompt_parser.set_defaults(handler=mcp_get_prompt)

    tools_parser = mcp_subparsers.add_parser("tools", help="Inspect or call MCP tools")
    tools_subparsers = tools_parser.add_subparsers(dest="mcp_tools_command", required=True)
    tools_list_parser = tools_subparsers.add_parser("list", help="List MCP tools")
    tools_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    tools_list_parser.set_defaults(handler=mcp_tools_list)

    tools_call_parser = tools_subparsers.add_parser("call", help="Call an MCP tool locally")
    tools_call_parser.add_argument("tool_name", help="MCP tool name")
    tools_call_parser.add_argument(
        "--args",
        dest="args_json",
        default="{}",
        help="Tool arguments as a JSON object",
    )
    tools_call_parser.add_argument("--args-json", dest="args_json", help=argparse.SUPPRESS)
    tools_call_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    tools_call_parser.set_defaults(handler=mcp_call)

    resources_parser = mcp_subparsers.add_parser("resources", help="Inspect MCP resources")
    resources_subparsers = resources_parser.add_subparsers(
        dest="mcp_resources_command",
        required=True,
    )
    resources_read_parser = resources_subparsers.add_parser(
        "read",
        help="Read an MCP resource locally",
    )
    resources_read_parser.add_argument("uri", help="MCP resource URI")
    resources_read_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    resources_read_parser.set_defaults(handler=mcp_read_resource)

    prompts_parser = mcp_subparsers.add_parser("prompts", help="Inspect MCP prompts")
    prompts_subparsers = prompts_parser.add_subparsers(dest="mcp_prompts_command", required=True)
    prompts_list_parser = prompts_subparsers.add_parser("list", help="List MCP prompts")
    prompts_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    prompts_list_parser.set_defaults(handler=mcp_prompts_list)

    prompts_get_parser = prompts_subparsers.add_parser("get", help="Get an MCP prompt locally")
    prompts_get_parser.add_argument("prompt_name", help="MCP prompt name")
    prompts_get_parser.add_argument(
        "--args",
        dest="args_json",
        default="{}",
        help="Prompt arguments as a JSON object",
    )
    prompts_get_parser.add_argument("--args-json", dest="args_json", help=argparse.SUPPRESS)
    prompts_get_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    prompts_get_parser.set_defaults(handler=mcp_get_prompt)

    serve_parser = mcp_subparsers.add_parser("serve-stdio", help="Run MCP stdio adapter")
    serve_parser.set_defaults(handler=mcp_serve_stdio)


def mcp_catalog(args: argparse.Namespace) -> int:
    service = _mcp_service()
    catalog = service.catalog().to_dict()
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False, sort_keys=True))
    else:
        print(f"tools={len(catalog['tools'])}")
        for tool in catalog["tools"]:
            print(f"- {tool['name']}: {tool['description']}")
        print(f"resources={len(catalog['resources'])}")
        for resource in catalog["resources"]:
            print(f"- {resource['uri']}: {resource['description']}")
        print(f"prompts={len(catalog['prompts'])}")
        for prompt in catalog["prompts"]:
            print(f"- {prompt['name']}: {prompt['description']}")
    return 0


def mcp_capabilities(args: argparse.Namespace) -> int:
    service = _mcp_service()
    manifest = service.capability_manifest().to_dict()
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    else:
        print(f"version={manifest['version']}")
        print(f"capabilities={manifest['capability_count']}")
        for capability in manifest["capabilities"]:
            print(
                f"- {capability['kind']} {capability['name']} "
                f"permission={capability['permission']} read_only={str(capability['read_only']).lower()}"
            )
    return 0


def mcp_tools_list(args: argparse.Namespace) -> int:
    service = _mcp_service()
    catalog = service.catalog().to_dict()
    tools = catalog.get("tools") or []
    payload = {"tool_count": len(tools), "tools": tools}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"tools={payload['tool_count']}")
        for tool in tools:
            print(f"- {tool['name']}: {tool['description']}")
    return 0


def mcp_prompts_list(args: argparse.Namespace) -> int:
    service = _mcp_service()
    catalog = service.catalog().to_dict()
    prompts = catalog.get("prompts") or []
    payload = {"prompt_count": len(prompts), "prompts": prompts}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"prompts={payload['prompt_count']}")
        for prompt in prompts:
            print(f"- {prompt['name']}: {prompt['description']}")
    return 0


def mcp_call(args: argparse.Namespace) -> int:
    service = _mcp_service()
    arguments = parse_json_object(args.args_json)
    result = service.call_tool(args.tool_name, arguments)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"tool_name={payload['tool_name']}")
        print(f"success={str(payload['success']).lower()}")
        if payload["error_message"]:
            print(f"error={payload['error_message']}")
        elif payload["data"] is not None:
            print(json.dumps(payload["data"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.success else 1


def mcp_read_resource(args: argparse.Namespace) -> int:
    service = _mcp_service()
    result = service.read_resource(args.uri)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"uri={payload['uri']}")
        print(f"success={str(payload['success']).lower()}")
        if payload["error_message"]:
            print(f"error={payload['error_message']}")
        elif payload["data"] is not None:
            print(json.dumps(payload["data"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.success else 1


def mcp_get_prompt(args: argparse.Namespace) -> int:
    service = _mcp_service()
    arguments = parse_json_object(args.args_json)
    result = service.get_prompt(args.prompt_name, arguments)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"name={payload['name']}")
        print(f"success={str(payload['success']).lower()}")
        if payload["error_message"]:
            print(f"error={payload['error_message']}")
        else:
            for message in payload["messages"]:
                print(f"[{message['role']}] {message['content']}")
    return 0 if result.success else 1


def parse_json_object(value: str) -> dict:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise SystemExit("--args-json must be a JSON object")
    return payload


def mcp_serve_stdio(args: argparse.Namespace) -> int:
    from interfaces.mcp.stdio_server import run_stdio

    run_stdio()
    return 0


def _mcp_service():
    return MCPApplicationService()


add_mcp_commands = register


__all__ = [
    "CommandHandler",
    "add_mcp_commands",
    "call_handler",
    "mcp_call",
    "mcp_capabilities",
    "mcp_catalog",
    "mcp_get_prompt",
    "mcp_prompts_list",
    "mcp_read_resource",
    "mcp_serve_stdio",
    "mcp_tools_list",
    "parse_json_object",
    "register",
]
