from __future__ import annotations


def normalize_dsn(dsn: str) -> str:
    """Normalize a Postgres DSN to the libpq/psycopg URI form.

    Strips a stray ``jdbc:`` prefix (a common copy-paste from JDBC configs that
    psycopg rejects with 'missing "=" after ...'). Centralizing this here means
    every psycopg.connect call site is protected by one function instead of each
    module defending itself.
    """
    if not dsn:
        return dsn
    return dsn.strip().removeprefix("jdbc:")


__all__ = ["normalize_dsn"]
