from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reader_repair_runtime_binding_bundle_has_one_application_owner() -> None:
    application_path = ROOT / "backend/research/application/reader_repair_runtime.py"
    composition_path = ROOT / "interfaces/composition/research.py"
    legacy_path = ROOT / "backend/research/application/single_paper_runtime.py"

    application_source = application_path.read_text(encoding="utf-8")
    composition_source = composition_path.read_text(encoding="utf-8")
    legacy_source = legacy_path.read_text(encoding="utf-8")
    assert "build_reader_repair_runtime_binding_bundle" in application_source
    assert "build_reader_repair_runtime_binding_bundle" not in composition_source
    assert "reader_repair_runtime" not in legacy_source


def test_reader_repair_runtime_registration_does_not_import_artifact_owners() -> None:
    source = (
        ROOT / "backend/research/graphs/reader_repair_runtime.py"
    ).read_text(encoding="utf-8")

    assert "framework.harness.artifacts" not in source
    assert "infrastructure.research.artifact" not in source
    assert "interfaces.composition.research_graph_artifacts" not in source
