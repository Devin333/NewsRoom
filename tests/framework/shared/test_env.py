from __future__ import annotations

from pathlib import Path

from framework import env as root_env


def test_load_root_env_preserves_existing_values(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "NEWS_TEST_VALUE=from-file",
                "NEWS_TEST_QUOTED='quoted value'",
                "IGNORED_WITHOUT_EQUALS",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(root_env, "_repo_root", lambda: tmp_path)
    monkeypatch.setenv("NEWS_TEST_VALUE", "from-process")
    monkeypatch.delenv("NEWS_TEST_QUOTED", raising=False)

    loaded_path = root_env.load_root_env()

    assert loaded_path == env_path
    assert root_env.os.environ["NEWS_TEST_VALUE"] == "from-process"
    assert root_env.os.environ["NEWS_TEST_QUOTED"] == "quoted value"


def test_load_root_env_can_override_existing_values(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("NEWS_TEST_VALUE=from-file", encoding="utf-8")
    monkeypatch.setattr(root_env, "_repo_root", lambda: tmp_path)
    monkeypatch.setenv("NEWS_TEST_VALUE", "from-process")

    root_env.load_root_env(override=True)

    assert root_env.os.environ["NEWS_TEST_VALUE"] == "from-file"


def test_env_values_from_root_returns_merged_copy(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("NEWS_TEST_VALUE=from-file", encoding="utf-8")
    monkeypatch.setattr(root_env, "_repo_root", lambda: tmp_path)
    monkeypatch.setenv("NEWS_TEST_EXISTING", "from-process")

    values = root_env.env_values_from_root()

    assert values["NEWS_TEST_VALUE"] == "from-file"
    assert values["NEWS_TEST_EXISTING"] == "from-process"
