from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_check_postgres_skips_without_dsn(monkeypatch, capsys) -> None:
    module = _load_script("check_postgres")
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)

    exit_code = module.main()

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["service"] == "postgres"
    assert output["status"] == "skipped"
    assert "NEWS_DATABASE_DSN" in output["reason"]


def test_check_qdrant_skips_without_url(monkeypatch, capsys) -> None:
    module = _load_script("check_qdrant")
    monkeypatch.delenv("NEWS_QDRANT_URL", raising=False)

    exit_code = module.main()

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["service"] == "qdrant"
    assert output["status"] == "skipped"
    assert "NEWS_QDRANT_URL" in output["reason"]


def _load_script(name: str):
    script_path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
