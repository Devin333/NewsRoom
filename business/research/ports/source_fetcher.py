from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SourcePackage(Protocol):
    """Minimal view of a fetched source package (e.g. arXiv e-print tarball)."""

    @property
    def content(self) -> bytes: ...

    @property
    def checksum(self) -> str: ...


@runtime_checkable
class SourceFetcherPort(Protocol):
    """Fetches the raw source package for a paper by its source id (e.g. arXiv id)."""

    def fetch_source_package(self, source_id: str) -> SourcePackage: ...


__all__ = ["SourceFetcherPort", "SourcePackage"]
