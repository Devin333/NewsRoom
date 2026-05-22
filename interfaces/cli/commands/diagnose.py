from __future__ import annotations

import argparse
import json

from interfaces.services.diagnose_service import DiagnosticApplicationService


def register(subparsers: argparse._SubParsersAction) -> None:
    diagnose_parser = subparsers.add_parser("diagnose", help="Run local diagnostics")
    diagnose_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    diagnose_parser.set_defaults(handler=diagnose)


def diagnose(args: argparse.Namespace) -> int:
    result = DiagnosticApplicationService().run()
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={payload['status']}")
        print(f"summary={payload['summary']}")
        for check in payload["checks"]:
            print(f"[{check['status'].upper()}] {check['name']}: {check['message']}")
            if check.get("remediation"):
                print(f"  fix={check['remediation']}")
    return 0 if result.status != "error" else 1


add_diagnose_commands = register


__all__ = ["add_diagnose_commands", "diagnose", "register"]
