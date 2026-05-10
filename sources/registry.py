from __future__ import annotations

from domain.sources import SourceDefinition


class SourceRegistry:
    def __init__(self, sources: list[SourceDefinition] | None = None) -> None:
        self._sources: dict[str, SourceDefinition] = {}
        for source in sources or []:
            self.register(source)

    def register(self, source: SourceDefinition) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"source already registered: {source.source_id}")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceDefinition:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise KeyError(f"source is not registered: {source_id}") from exc

    def list_sources(self, *, enabled_only: bool = True) -> list[SourceDefinition]:
        sources = list(self._sources.values())
        if enabled_only:
            sources = [source for source in sources if source.enabled]
        return sorted(sources, key=lambda source: source.source_id)
