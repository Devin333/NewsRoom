"""Deprecated worker handler compatibility module.

Business task handlers live in :mod:`business.workers`.
"""

from __future__ import annotations


__all__: list[str] = []


def __getattr__(name: str) -> object:
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}; "
        "business task handlers are exported from 'business.workers'"
    )
