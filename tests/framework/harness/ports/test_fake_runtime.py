from __future__ import annotations

from framework.harness import (
    ArtifactWriteRequest,
    FakeArtifactPort,
    FakeLLMWorker,
    FakeQualityGate,
    HarnessQualityVerdict,
    HarnessWorkerResult,
)


def test_fake_artifact_port_write_returns_ref() -> None:
    artifacts = FakeArtifactPort()
    ref = artifacts.write_artifact(ArtifactWriteRequest(artifact_type="report", payload={"title": "ok"}))

    assert ref.ref == "artifact://fake/1"
    assert ref.checksum.startswith("sha256:")
    assert artifacts.read_artifact(ref.ref)["payload"] == {"title": "ok"}


def test_fake_quality_gate_returns_configured_verdict() -> None:
    gate = FakeQualityGate(HarnessQualityVerdict(passed=False, score=0.2, issues=("missing evidence",)))
    verdict = gate.evaluate({"artifact_ref": "artifact://fake/1"})

    assert verdict.passed is False
    assert gate.contexts[0]["artifact_ref"] == "artifact://fake/1"


def test_fake_worker_returns_configured_worker_result() -> None:
    worker = FakeLLMWorker((HarnessWorkerResult(status="succeeded", output={"candidate": "ok"}),))

    assert worker.generate({"context": {"token_estimate": 1}}).output == {"candidate": "ok"}
