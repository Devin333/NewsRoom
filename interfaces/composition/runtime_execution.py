"""Research process execution composition.

The process owns one registry and one manifest.  Individual parser adapters
receive only the profile they are allowed to use; they cannot create a local
provider or downgrade to host execution.
"""

from __future__ import annotations

from framework.execution_environment import (
    ExecutionEnvironmentRegistry,
    ExecutionProfile,
    ExecutionProfileRegistry,
    RuntimeCompositionManifest,
    RuntimeExecutionComposition,
    build_runtime_execution_composition,
)
from infrastructure.execution_environment.docker import DockerExecutionEnvironment


RESEARCH_RUNTIME_COMPOSITION_ID = "research-runtime"
RESEARCH_RUNTIME_COMPOSITION_VERSION = "1"
RESEARCH_MARKER_PROFILE_ID = "research-parser-marker"
RESEARCH_MINERU_PROFILE_ID = "research-parser-mineru"


def build_research_execution_composition() -> RuntimeExecutionComposition:
    """Build the process-scoped Research execution composition.

    Docker availability is intentionally represented in the provider
    capability fingerprint.  An unavailable daemon remains a typed admission
    block; this factory never substitutes an in-process or host subprocess
    provider.
    """

    execution_registry = ExecutionEnvironmentRegistry()
    execution_registry.register(DockerExecutionEnvironment())
    profile_registry = ExecutionProfileRegistry()
    profile_registry.register(
        RESEARCH_MARKER_PROFILE_ID,
        ExecutionProfile.external_process(
            provider_id="docker",
            allowed_argv_prefixes=(("marker_single",),),
        ),
    )
    profile_registry.register(
        RESEARCH_MINERU_PROFILE_ID,
        ExecutionProfile.external_process(
            provider_id="docker",
            allowed_argv_prefixes=(("mineru",),),
        ),
    )
    manifest = RuntimeCompositionManifest.from_registries(
        composition_id=RESEARCH_RUNTIME_COMPOSITION_ID,
        version=RESEARCH_RUNTIME_COMPOSITION_VERSION,
        profile_registry=profile_registry,
        execution_registry=execution_registry,
        metadata={
            "role": "research",
            "parser_profiles": {
                "marker": RESEARCH_MARKER_PROFILE_ID,
                "mineru": RESEARCH_MINERU_PROFILE_ID,
            },
        },
    )
    return build_runtime_execution_composition(
        manifest=manifest,
        profile_registry=profile_registry,
        execution_registry=execution_registry,
    )


__all__ = [
    "RESEARCH_MARKER_PROFILE_ID",
    "RESEARCH_MINERU_PROFILE_ID",
    "RESEARCH_RUNTIME_COMPOSITION_ID",
    "RESEARCH_RUNTIME_COMPOSITION_VERSION",
    "build_research_execution_composition",
]
