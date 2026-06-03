from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConnectorMetadataFallbackPhase:
    phase_id: str
    source_type: str
    legacy_keys: tuple[str, ...]
    formal_fields: tuple[str, ...]
    exit_criteria: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "phase_id": self.phase_id,
            "source_type": self.source_type,
            "legacy_keys": list(self.legacy_keys),
            "formal_fields": list(self.formal_fields),
            "exit_criteria": list(self.exit_criteria),
        }


def source_connector_metadata_fallback_deprecation_plan() -> tuple[
    SourceConnectorMetadataFallbackPhase,
    ...
]:
    return (
        SourceConnectorMetadataFallbackPhase(
            phase_id="phase-1-github-mode",
            source_type="github",
            legacy_keys=("mode",),
            formal_fields=("github_mode",),
            exit_criteria=(
                "All GitHub sources use metadata.github_mode instead of metadata.mode.",
                "Source connector option tests no longer require legacy GitHub mode fallback.",
            ),
        ),
        SourceConnectorMetadataFallbackPhase(
            phase_id="phase-2-reddit-time",
            source_type="reddit",
            legacy_keys=("time",),
            formal_fields=("time_range",),
            exit_criteria=(
                "All Reddit sources use metadata.time_range instead of metadata.time.",
                "Source connector option tests no longer require legacy Reddit time fallback.",
            ),
        ),
        SourceConnectorMetadataFallbackPhase(
            phase_id="phase-3-stackoverflow-tag",
            source_type="stackoverflow",
            legacy_keys=("tag",),
            formal_fields=("tagged",),
            exit_criteria=(
                "StackOverflow sources use metadata.tagged for question tags.",
                "Shared community sources continue to use metadata.tag through SourceConnectorRuntimeOptions.tag.",
            ),
        ),
        SourceConnectorMetadataFallbackPhase(
            phase_id="phase-4-manual-records-shape",
            source_type="manual",
            legacy_keys=("records",),
            formal_fields=("manual_records",),
            exit_criteria=(
                "Manual source fixtures/configs provide a typed manual_records payload.",
                "Manual connector no longer relies on arbitrary metadata.records shape checks.",
            ),
        ),
    )


def source_connector_metadata_fallback_legacy_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for phase in source_connector_metadata_fallback_deprecation_plan():
        for key in phase.legacy_keys:
            if key not in keys:
                keys.append(key)
    return tuple(keys)


__all__ = [
    "SourceConnectorMetadataFallbackPhase",
    "source_connector_metadata_fallback_deprecation_plan",
    "source_connector_metadata_fallback_legacy_keys",
]
