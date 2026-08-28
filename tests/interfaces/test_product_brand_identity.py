from __future__ import annotations

import json
import tomllib
from pathlib import Path

from interfaces.api import create_app
from interfaces.mcp.models import MCPCapabilityManifest


ROOT = Path(__file__).resolve().parents[2]


def test_public_brand_and_distribution_metadata_are_agora_hub() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "agora-hub"
    assert "news, research papers, and projects" in project["description"]
    assert project["authors"][0]["name"] == "Agora Hub"
    assert project["urls"]["Repository"] == "https://github.com/Devin333/Agora-Hub"

    for relative_path, expected_name in (
        ("frontend/package.json", "agora-hub-reader-portal"),
        ("apps/web/package.json", "agora-hub-web-console"),
        ("frontend/package-lock.json", "agora-hub-reader-portal"),
        ("apps/web/package-lock.json", "agora-hub-web-console"),
    ):
        payload = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
        assert payload["name"] == expected_name

    assert create_app(audit_emitter_factory=None).title == "Agora Hub API"
    assert MCPCapabilityManifest(version="0.1.0", capabilities=[]).server_name == "Agora Hub"
    openapi = json.loads((ROOT / "docs/api/openapi.json").read_text(encoding="utf-8"))
    assert openapi["info"]["title"] == "Agora Hub API"


def test_legacy_runtime_identifiers_remain_available() -> None:
    session_source = (ROOT / "frontend/src/lib/auth/session.ts").read_text(encoding="utf-8")
    env_source = (ROOT / "frontend/src/lib/api/client.ts").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'NEWSROOM_SESSION_COOKIE = "newsroom_session"' in session_source
    assert "NEXT_PUBLIC_NEWSROOM_API_BASE_URL" in env_source
    assert ".newsroom/runs" in readme
    assert (ROOT / "sdk/python/newsroom_sdk/__init__.py").is_file()
