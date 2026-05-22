from __future__ import annotations

import argparse
import json

from business.tools import build_business_tool_registry
from framework.tool import ToolPolicy, build_tool_catalog
from interfaces.cli.commands.dispatch import CommandHandler, call_handler


def register(subparsers: argparse._SubParsersAction) -> None:
    tools_parser = subparsers.add_parser("tools", help="Discover Tool Runtime tools")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command", required=True)

    list_parser = tools_subparsers.add_parser("list", help="List built-in tool catalog")
    add_tool_policy_args(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_tools)

    schema_parser = tools_subparsers.add_parser(
        "schema",
        help="Export built-in tool schemas after applying a tool policy",
    )
    add_tool_policy_args(schema_parser)
    schema_parser.add_argument("--agent-id", default="cli", help="Agent id for policy export")
    schema_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    schema_parser.set_defaults(handler=schema)


def add_tool_policy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allowed",
        dest="allowed_tools",
        action="append",
        default=None,
        help="Allowed tool name; can be passed multiple times",
    )
    parser.add_argument(
        "--blocked",
        dest="blocked_tools",
        action="append",
        default=None,
        help="Blocked tool name; can be passed multiple times",
    )
    parser.add_argument(
        "--allow-mcp",
        action="store_true",
        help="Expose MCP tools if present in the registry",
    )
    parser.add_argument(
        "--include-dangerous",
        action="store_true",
        help="Expose dangerous tools if present in the registry",
    )


def list_tools(args: argparse.Namespace) -> int:
    registry = build_business_tool_registry(include_dangerous_tools=bool(args.include_dangerous))
    catalog = build_tool_catalog(
        registry,
        agent_id="cli",
        policy=tool_policy_from_args(args),
    )
    payload = catalog.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"tool_count={payload['tool_count']}")
        print(f"namespace_count={payload['namespace_count']}")
        for namespace in payload["namespaces"]:
            print(f"- {namespace['namespace']} tools={namespace['tool_count']}")
        for tool in payload["tools"]:
            print(f"{tool['name']}@{tool['version']} side_effect={tool['side_effect']}")
    return 0 if catalog.registry_valid else 1


def schema(args: argparse.Namespace) -> int:
    registry = build_business_tool_registry(include_dangerous_tools=bool(args.include_dangerous))
    tools = registry.export_schema_for_llm(args.agent_id, tool_policy_from_args(args))
    payload = {
        "agent_id": args.agent_id,
        "tool_count": len(tools),
        "tools": tools,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"agent_id={payload['agent_id']}")
        print(f"tool_count={payload['tool_count']}")
        for tool in payload["tools"]:
            print(f"- {tool['name']}@{tool['version']}")
    return 0


def tool_policy_from_args(args: argparse.Namespace) -> ToolPolicy:
    allowed_tools = list(args.allowed_tools or [])
    return ToolPolicy(
        allowed_tools=allowed_tools,
        blocked_tools=list(args.blocked_tools or []),
        allow_mcp_tools=bool(args.allow_mcp),
        allow_dangerous_tools=bool(args.include_dangerous),
        require_explicit_allowlist=bool(allowed_tools),
    )


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


add_tools_commands = register


__all__ = [
    "CommandHandler",
    "add_tool_policy_args",
    "add_tools_commands",
    "call_handler",
    "list_tools",
    "register",
    "schema",
    "tool_policy_from_args",
]
