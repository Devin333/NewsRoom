from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from interfaces.api.openapi import summarize_openapi_schema, write_openapi_schema


DEFAULT_OUTPUT = Path("docs/api/openapi.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.export_openapi")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="OpenAPI JSON output path")
    parser.add_argument("--summary", action="store_true", help="Print schema summary")
    args = parser.parse_args(argv)

    schema = write_openapi_schema(args.output)
    if args.summary:
        print(json.dumps(summarize_openapi_schema(schema), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
