from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reader_repair_runtime_binding_bundle_is_not_in_production_composition() -> None:
    production_callers = (
        ROOT / "business/research/application/single_paper_runtime.py",
        ROOT / "interfaces/composition/research.py",
    )

    for path in production_callers:
        source = path.read_text(encoding="utf-8")
        assert "reader_repair_runtime" not in source
        assert "build_reader_repair_runtime_binding_bundle" not in source


def test_reader_repair_runtime_registration_does_not_import_artifact_owners() -> None:
    source = (
        ROOT / "business/research/graphs/reader_repair_runtime.py"
    ).read_text(encoding="utf-8")

    assert "framework.harness.artifacts" not in source
    assert "infrastructure.research.artifact" not in source
    assert "interfaces.composition.research_graph_artifacts" not in source
