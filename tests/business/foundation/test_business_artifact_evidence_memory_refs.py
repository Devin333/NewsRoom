from __future__ import annotations

from business.foundation import (
    BusinessArtifactRef,
    BusinessEvidenceRef,
    BusinessMemoryRef,
    BusinessRunManifestRef,
    BusinessTraceRef,
    SourceRef,
    SourceType,
)


def test_business_artifact_evidence_memory_refs_are_traceable() -> None:
    source = SourceRef(source_name="Source", source_type=SourceType.MANUAL, url="manual://source")
    trace = BusinessTraceRef.create(run_id="run-1", workflow_id="wf-1", source_ref=source)
    manifest = BusinessRunManifestRef.create(run_id="run-1", source_ref=source, artifact_ids=["artifact-1"])
    artifact = BusinessArtifactRef.create(
        "board_output",
        label="Board Output",
        run_id="run-1",
        trace_ref=source,
        manifest_ref=source,
        source_ref=source,
    )
    evidence = BusinessEvidenceRef.from_source(source, relation_ids=["rel-1"], signal_ids=["sig-1"], confidence=0.8)
    memory = BusinessMemoryRef.create(query="agent memory", source_ref=source, score=0.7)

    assert artifact.artifact_id.startswith("artifact_")
    assert evidence.evidence_id.startswith("evidence_")
    assert memory.memory_id.startswith("memory_")
    assert trace.trace_id.startswith("trace_")
    assert manifest.manifest_id.startswith("manifest_")
    assert evidence.source_ref.source_id == source.source_id
