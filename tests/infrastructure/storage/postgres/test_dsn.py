from __future__ import annotations

from infrastructure.storage.postgres.dsn import normalize_dsn


def test_strips_jdbc_prefix():
    assert normalize_dsn("jdbc:postgresql://localhost:5432/db") == "postgresql://localhost:5432/db"


def test_standard_dsn_unchanged():
    dsn = "postgresql://user:pw@host:5432/db"
    assert normalize_dsn(dsn) == dsn


def test_empty_passthrough():
    assert normalize_dsn("") == ""


def test_whitespace_trimmed():
    assert normalize_dsn("  jdbc:postgresql://h/db  ") == "postgresql://h/db"


def test_only_leading_jdbc_stripped():
    # 'jdbc:' is only a prefix; an internal occurrence must survive
    assert normalize_dsn("postgresql://h/jdbc:weird") == "postgresql://h/jdbc:weird"
