from __future__ import annotations

import argparse
import json
import sys

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.artifact_service import ArtifactInspectionService


def register(subparsers: argparse._SubParsersAction) -> None:
    artifacts_parser = subparsers.add_parser("artifacts", help="Inspect run artifacts")
    artifacts_subparsers = artifacts_parser.add_subparsers(dest="artifacts_command", required=True)

    list_parser = artifacts_subparsers.add_parser("list", help="List artifacts for a run")
    list_parser.add_argument("--run-id", required=True, help="Run id")
    _add_artifact_root(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_artifacts)

    show_parser = artifacts_subparsers.add_parser("show", help="Show a run artifact")
    show_parser.add_argument("--run-id", required=True, help="Run id")
    show_parser.add_argument("--artifact-key", required=True, help="Artifact key from manifest")
    _add_artifact_root(show_parser)
    show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    show_parser.set_defaults(handler=show_artifact)


def list_artifacts(args: argparse.Namespace) -> int:
    try:
        result = _artifact_service(artifact_root=args.artifact_root).list_artifacts(args.run_id)
    except _TYPED_ARTIFACT_ERRORS as exc:
        _print_typed_artifact_error(exc)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"run_id={payload['run_id']}")
        print(f"artifact_count={payload['artifact_count']}")
        for artifact in payload["artifacts"]:
            print(
                f"- {artifact['artifact_key']} path={artifact['relative_path']} "
                f"type={artifact['content_type']} size={artifact['size_bytes']}"
            )
    return 0


def show_artifact(args: argparse.Namespace) -> int:
    try:
        result = _artifact_service(artifact_root=args.artifact_root).get_artifact(
            args.run_id,
            args.artifact_key,
        )
    except _TYPED_ARTIFACT_ERRORS as exc:
        _print_typed_artifact_error(exc)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    elif isinstance(payload["content"], str):
        print(payload["content"])
    else:
        print(json.dumps(payload["content"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _artifact_service(*args, **kwargs):
    return ArtifactInspectionService(*args, **kwargs)


def _add_artifact_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _print_typed_artifact_error(exc: Exception) -> None:
    print(str(exc), file=sys.stderr)


_TYPED_ARTIFACT_ERRORS = (
    ArtifactPathError,
    ArtifactChecksumMismatchError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)


add_artifacts_commands = register


__all__ = [
    "CommandHandler",
    "add_artifacts_commands",
    "call_handler",
    "list_artifacts",
    "register",
    "show_artifact",
]
