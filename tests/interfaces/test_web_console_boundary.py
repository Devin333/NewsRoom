from pathlib import Path
import re

from interfaces.api.schema import export_openapi_schema


BOUNDARY_PATH = Path("interfaces/web_console_boundary.md")


def test_web_console_boundary_declares_http_only_pages() -> None:
    text = BOUNDARY_PATH.read_text(encoding="utf-8")

    assert "must not import storage, workflow" in text
    assert "must not read or" in text
    for section in (
        "## Runs Page",
        "## Reports Page",
        "## Sources Page",
        "## Workers Page",
        "## Approvals Page",
        "## Memory Page",
    ):
        assert section in text


def test_web_console_boundary_paths_exist_in_openapi_schema() -> None:
    text = BOUNDARY_PATH.read_text(encoding="utf-8")
    schema_paths = export_openapi_schema()["paths"]
    api_paths = sorted(set(re.findall(r"`(?:GET|POST|PATCH|DELETE) (/api/v1/[^`]+)`", text)))

    assert api_paths
    missing = [path for path in api_paths if path not in schema_paths]

    assert missing == []
