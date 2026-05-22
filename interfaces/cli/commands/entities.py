from __future__ import annotations

import argparse
import json
from typing import Any, Protocol

from interfaces.services.entity_service import DEFAULT_ENTITY_STORE_PATH


ENTITY_KIND_CHOICES = ["company", "project", "person", "organization"]


class EntityServiceFactory(Protocol):
    def __call__(self, *, store_path: str) -> Any:
        ...


def register(subparsers: argparse._SubParsersAction) -> None:
    entities_parser = subparsers.add_parser("entities", help="Manage tracked entities")
    entities_subparsers = entities_parser.add_subparsers(dest="entities_command", required=True)

    create_parser = entities_subparsers.add_parser(
        "create",
        help="Create or update a tracked entity",
    )
    create_parser.add_argument("--name", required=True, help="Entity display name")
    create_parser.add_argument("--kind", choices=ENTITY_KIND_CHOICES, default="company")
    create_parser.add_argument("--entity-id", default=None, help="Optional entity id")
    create_parser.add_argument("--alias", action="append", default=None, help="Alias; repeatable")
    create_parser.add_argument("--disabled", action="store_true")
    create_parser.add_argument(
        "--metadata",
        action="append",
        default=None,
        help="Metadata key=value; repeat for multiple values",
    )
    _add_store_path(create_parser)
    create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    create_parser.set_defaults(handler=create_entity_from_cli)

    list_parser = entities_subparsers.add_parser("list", help="List tracked entities")
    list_parser.add_argument("--enabled-only", action="store_true")
    list_parser.add_argument("--kind", choices=ENTITY_KIND_CHOICES, default=None)
    _add_store_path(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_entities_from_cli)

    enable_parser = entities_subparsers.add_parser("enable", help="Enable a tracked entity")
    enable_parser.add_argument("entity_id")
    _add_store_path(enable_parser)
    enable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    enable_parser.set_defaults(handler=enable_entity_from_cli)

    disable_parser = entities_subparsers.add_parser("disable", help="Disable a tracked entity")
    disable_parser.add_argument("entity_id")
    _add_store_path(disable_parser)
    disable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    disable_parser.set_defaults(handler=disable_entity_from_cli)

    delete_parser = entities_subparsers.add_parser("delete", help="Delete a tracked entity")
    delete_parser.add_argument("entity_id")
    _add_store_path(delete_parser)
    delete_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    delete_parser.set_defaults(handler=delete_entity_from_cli)

    match_parser = entities_subparsers.add_parser(
        "match-reports",
        help="Match a tracked entity against persisted reports",
    )
    match_parser.add_argument("entity_id")
    _add_store_path(match_parser)
    match_parser.add_argument("--artifact-root", default=".newsroom/runs")
    match_parser.add_argument("--limit", type=int, default=20)
    match_parser.add_argument("--workflow-id", default=None)
    match_parser.add_argument("--workflow-family", default=None)
    match_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    match_parser.set_defaults(handler=match_entity_reports_from_cli)


def create_entity_from_cli(args: argparse.Namespace) -> int:
    from interfaces.cli import news as news_cli

    return create_entity(
        args,
        entity_service_factory=news_cli.EntityTrackingApplicationService,
    )


def list_entities_from_cli(args: argparse.Namespace) -> int:
    from interfaces.cli import news as news_cli

    return list_entities(
        args,
        entity_service_factory=news_cli.EntityTrackingApplicationService,
    )


def enable_entity_from_cli(args: argparse.Namespace) -> int:
    return set_entity_enabled_from_cli(args, enabled=True)


def disable_entity_from_cli(args: argparse.Namespace) -> int:
    return set_entity_enabled_from_cli(args, enabled=False)


def set_entity_enabled_from_cli(args: argparse.Namespace, *, enabled: bool) -> int:
    from interfaces.cli import news as news_cli

    return set_entity_enabled(
        args,
        enabled=enabled,
        entity_service_factory=news_cli.EntityTrackingApplicationService,
    )


def delete_entity_from_cli(args: argparse.Namespace) -> int:
    from interfaces.cli import news as news_cli

    return delete_entity(
        args,
        entity_service_factory=news_cli.EntityTrackingApplicationService,
    )


def match_entity_reports_from_cli(args: argparse.Namespace) -> int:
    from interfaces.cli import news as news_cli

    return match_entity_reports(
        args,
        entity_service_factory=news_cli.EntityTrackingApplicationService,
    )


def create_entity(
    args: argparse.Namespace,
    *,
    entity_service_factory: EntityServiceFactory,
) -> int:
    try:
        entity = entity_service_factory(store_path=args.store_path).create_entity(
            name=args.name,
            kind=args.kind,
            aliases=args.alias or [],
            entity_id=args.entity_id,
            enabled=not args.disabled,
            metadata=parse_key_values(args.metadata or []),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    return print_entity(entity.to_dict(), json_output=args.json)


def list_entities(
    args: argparse.Namespace,
    *,
    entity_service_factory: EntityServiceFactory,
) -> int:
    try:
        result = entity_service_factory(store_path=args.store_path).list_entities(
            enabled_only=args.enabled_only,
            kind=args.kind,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"entity_count={payload['entity_count']}")
        for item in payload["entities"]:
            state = "enabled" if item["enabled"] else "disabled"
            print(f"- {item['entity_id']} {state} kind={item['kind']} name={item['name']}")
    return 0


def set_entity_enabled(
    args: argparse.Namespace,
    *,
    enabled: bool,
    entity_service_factory: EntityServiceFactory,
) -> int:
    try:
        entity = entity_service_factory(store_path=args.store_path).set_enabled(
            args.entity_id,
            enabled=enabled,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    return print_entity(entity.to_dict(), json_output=args.json)


def delete_entity(
    args: argparse.Namespace,
    *,
    entity_service_factory: EntityServiceFactory,
) -> int:
    deleted = entity_service_factory(store_path=args.store_path).delete_entity(args.entity_id)
    payload = {"entity_id": args.entity_id, "deleted": deleted}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"deleted={str(deleted).lower()}")
    return 0


def match_entity_reports(
    args: argparse.Namespace,
    *,
    entity_service_factory: EntityServiceFactory,
) -> int:
    try:
        result = entity_service_factory(store_path=args.store_path).match_reports(
            args.entity_id,
            artifact_root=args.artifact_root,
            limit=args.limit,
            workflow_id=args.workflow_id,
            workflow_family=args.workflow_family,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"match_count={payload['match_count']}")
        for item in payload["matches"]:
            aliases = ",".join(item["matched_aliases"])
            print(f"- {item['report_id']} aliases={aliases} title={item['title']}")
    return 0


def print_entity(payload: dict, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        state = "enabled" if payload["enabled"] else "disabled"
        print(f"entity_id={payload['entity_id']}")
        print(f"name={payload['name']}")
        print(f"kind={payload['kind']}")
        print(f"state={state}")
    return 0


def parse_key_values(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid metadata '{value}', expected key=value")
        key, parsed_value = value.split("=", 1)
        if not key:
            raise ValueError(f"invalid metadata '{value}', expected key=value")
        parsed[key] = parsed_value
    return parsed


def _add_store_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)


add_entities_commands = register


__all__ = [
    "ENTITY_KIND_CHOICES",
    "EntityServiceFactory",
    "add_entities_commands",
    "create_entity",
    "create_entity_from_cli",
    "delete_entity",
    "delete_entity_from_cli",
    "disable_entity_from_cli",
    "enable_entity_from_cli",
    "list_entities",
    "list_entities_from_cli",
    "match_entity_reports",
    "match_entity_reports_from_cli",
    "parse_key_values",
    "print_entity",
    "register",
    "set_entity_enabled",
    "set_entity_enabled_from_cli",
]
