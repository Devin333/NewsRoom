from __future__ import annotations

import argparse
import json

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
    result = _tool_service().list_tools(
        allowed_tools=args.allowed_tools,
        blocked_tools=args.blocked_tools,
        allow_mcp=bool(args.allow_mcp),
        include_dangerous=bool(args.include_dangerous),
    )
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"tool_count={payload['tool_count']}")
        print(f"namespace_count={payload['namespace_count']}")
        for namespace in payload["namespaces"]:
            print(f"- {namespace['namespace']} tools={namespace['tool_count']}")
        for tool in payload["tools"]:
            print(f"{tool['name']}@{tool['version']} side_effect={tool['side_effect']}")
    return 0 if result.registry_valid else 1


def schema(args: argparse.Namespace) -> int:
    result = _tool_service().export_schema(
        agent_id=args.agent_id,
        allowed_tools=args.allowed_tools,
        blocked_tools=args.blocked_tools,
        allow_mcp=bool(args.allow_mcp),
        include_dangerous=bool(args.include_dangerous),
    )
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"agent_id={payload['agent_id']}")
        print(f"tool_count={payload['tool_count']}")
        for tool in payload["tools"]:
            print(f"- {tool['name']}@{tool['version']}")
    return 0


def tool_policy_from_args(args: argparse.Namespace):
    return _tool_service().tool_policy(
        allowed_tools=args.allowed_tools,
        blocked_tools=args.blocked_tools,
        allow_mcp=bool(args.allow_mcp),
        include_dangerous=bool(args.include_dangerous),
    )


def _tool_service():
    from interfaces.cli import news as news_cli

    return news_cli.ToolApplicationService()


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
