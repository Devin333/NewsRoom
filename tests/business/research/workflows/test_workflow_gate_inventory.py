from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from pathlib import Path

import pytest

import business.research.workflows as research_workflows
from business.research.workflows import build_paper_analysis_workflow_spec
from framework.harness.control_plane.gate_registry import GateReference
from framework.harness.graph import HarnessWorkerType


_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_WORKFLOW_PACKAGE = Path(research_workflows.__file__).resolve().parent
_PRODUCTION_ROOTS = tuple(
    _REPOSITORY_ROOT / name
    for name in ("business", "framework", "infrastructure", "interfaces", "scripts")
)
_SIDE_EFFECT_WORKER_TYPES = frozenset(
    {
        HarnessWorkerType.ARTIFACT,
        HarnessWorkerType.MEMORY,
        HarnessWorkerType.SKILL_EVOLUTION,
    }
)
_RUNTIME_REFERENCE_SUFFIXES = frozenset(
    {".json", ".jsonl", ".toml", ".yaml", ".yml"}
)
_RUNTIME_REFERENCE_ROOTS = tuple(
    _REPOSITORY_ROOT / name
    for name in (
        "business",
        "framework",
        "infrastructure",
        "interfaces",
        "scripts",
        "sdk",
        "tests",
    )
)
_RETIRED_WORKFLOW_RUNTIME_TOKENS = frozenset(
    {
        "business.research.workflows.paper_rag_workflow",
        "business.research.workflows.reader_repair_workflow",
        "build_paper_rag_workflow_spec",
        "build_reader_repair_workflow_spec",
        "build_retrieval_goal",
        "verify_retrieval_plan",
        "project_to_evidence_pack",
        "detect_reader_issue",
        "build_repair_memory_query",
        "commit_repair_episode_memory",
    }
)


_REMOVED_GATE_DECLARATIONS = (
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "build_retrieval_goal",
        "ResearchRetrievalGoalGate",
        id="paper-rag/retrieval-goal",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "plan_retrieval",
        "RetrievalPlanSchemaGate",
        id="paper-rag/retrieval-plan",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "verify_retrieval_plan",
        "ResearchRAGSourceScopeGate",
        id="paper-rag/plan-source-scope",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "execute_retrieval_round",
        "BoundedRAGBudgetGate",
        id="paper-rag/budget",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "verify_rag_sources",
        "ResearchRAGSourceScopeGate",
        id="paper-rag/result-source-scope",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "assemble_research_context",
        "ResearchRAGContextProjectionGate",
        id="paper-rag/context-projection",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "verify_research_context",
        "ResearchEvidenceCoverageGate",
        id="paper-rag/evidence-coverage",
    ),
    pytest.param(
        "paper_rag_workflow",
        "build_paper_rag_workflow_spec",
        "project_to_evidence_pack",
        "ResearchEvidencePackGate",
        id="paper-rag/evidence-pack",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "detect_reader_issue",
        "ReaderIssueSchemaGate",
        id="reader-repair/issue-schema",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "build_repair_memory_query",
        "RepairMemoryNamespaceGate",
        id="reader-repair/query-namespace",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "recall_repair_memory",
        "RepairMemoryPolicyGate",
        id="reader-repair/recall-policy",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "run_repair_rag",
        "ResearchRAGMemoryNamespaceGate",
        id="reader-repair/rag-namespace",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "build_repair_context_pack",
        "ReaderRepairSourceLineageGate",
        id="reader-repair/source-lineage",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "propose_repair_candidate",
        "ReaderRepairCandidateSchemaGate",
        id="reader-repair/candidate-schema",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "verify_repair_candidate",
        "ReaderRepairPayloadFidelityGate",
        id="reader-repair/candidate-fidelity",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "apply_repair",
        "ReaderPayloadSchemaGate",
        id="reader-repair/payload-schema",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "verify_reader_payload",
        "ReaderRepairPayloadFidelityGate",
        id="reader-repair/payload-fidelity",
    ),
    pytest.param(
        "reader_repair_workflow",
        "build_reader_repair_workflow_spec",
        "commit_repair_episode_memory",
        "ReaderRepairMemoryPolicyGate",
        id="reader-repair/memory-commit-policy",
    ),
)

_GATE_DISPOSITION_INVENTORY = {
    (
        "paper_rag_workflow",
        "build_retrieval_goal",
        "ResearchRetrievalGoalGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "plan_retrieval",
        "RetrievalPlanSchemaGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "verify_retrieval_plan",
        "ResearchRAGSourceScopeGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "execute_retrieval_round",
        "BoundedRAGBudgetGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "verify_rag_sources",
        "ResearchRAGSourceScopeGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "assemble_research_context",
        "ResearchRAGContextProjectionGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "verify_research_context",
        "ResearchEvidenceCoverageGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "paper_rag_workflow",
        "project_to_evidence_pack",
        "ResearchEvidencePackGate",
    ): (
        "removed",
        "business.research.application.paper_rag_session",
        "PaperRAGSession",
    ),
    (
        "reader_repair_workflow",
        "detect_reader_issue",
        "ReaderIssueSchemaGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_service",
        "ReaderRepairService",
    ),
    (
        "reader_repair_workflow",
        "build_repair_memory_query",
        "RepairMemoryNamespaceGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "recall_repair_memory",
        "RepairMemoryPolicyGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "run_repair_rag",
        "ResearchRAGMemoryNamespaceGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "build_repair_context_pack",
        "ReaderRepairSourceLineageGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "propose_repair_candidate",
        "ReaderRepairCandidateSchemaGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "verify_repair_candidate",
        "ReaderRepairPayloadFidelityGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "apply_repair",
        "ReaderPayloadSchemaGate",
    ): (
        "removed",
        "business.research.reader_repair.repair_service",
        "ReaderRepairService",
    ),
    (
        "reader_repair_workflow",
        "verify_reader_payload",
        "ReaderRepairPayloadFidelityGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "reader_repair_workflow",
        "commit_repair_episode_memory",
        "ReaderRepairMemoryPolicyGate",
    ): (
        "precondition-owned",
        "business.research.reader_repair.repair_gates",
        "ReaderRepairGateSuite",
    ),
    (
        "paper_analysis_workflow",
        "publish_artifacts",
        "ArtifactPublicationGate",
    ): (
        "removed",
        "business.research.application.single_paper_runtime",
        "ResearchSinglePaperRuntime",
    ),
}


@pytest.mark.parametrize(
    ("module_name", "builder_name", "step_id", "gate_id"),
    _REMOVED_GATE_DECLARATIONS,
)
def test_removed_gate_declaration_inventory_stays_retired(
    module_name: str,
    builder_name: str,
    step_id: str,
    gate_id: str,
) -> None:
    assert not (_WORKFLOW_PACKAGE / f"{module_name}.py").exists(), (
        f"{step_id}:{gate_id} belonged to a declarative workflow with no production "
        "controller path; reconnect the real controller before restoring it"
    )
    assert builder_name not in research_workflows.__all__


def test_retired_gate_inventory_names_disposition_and_canonical_owner() -> None:
    declared = {
        (parameter.values[0], parameter.values[2], parameter.values[3])
        for parameter in _REMOVED_GATE_DECLARATIONS
    }
    declared.add(
        (
            "paper_analysis_workflow",
            "publish_artifacts",
            "ArtifactPublicationGate",
        )
    )

    assert set(_GATE_DISPOSITION_INVENTORY) == declared
    for disposition, owner_module, owner_name in _GATE_DISPOSITION_INVENTORY.values():
        assert disposition in {"removed", "precondition-owned"}
        assert getattr(import_module(owner_module), owner_name) is not None


@pytest.mark.parametrize(
    ("module_name", "builder_name", "canonical_owner"),
    (
        pytest.param(
            "paper_rag_workflow",
            "build_paper_rag_workflow_spec",
            "business.research.application.paper_rag_session.PaperRAGSession",
            id="paper-rag",
        ),
        pytest.param(
            "reader_repair_workflow",
            "build_reader_repair_workflow_spec",
            "business.research.reader_repair.repair_service.ReaderRepairService",
            id="reader-repair",
        ),
    ),
)
def test_retired_workflow_builder_has_no_production_reference(
    module_name: str,
    builder_name: str,
    canonical_owner: str,
) -> None:
    owner_module, owner_name = canonical_owner.rsplit(".", maxsplit=1)
    references = _production_references(module_name, builder_name)

    assert getattr(import_module(owner_module), owner_name) is not None
    assert not references, (
        f"retired builder competes with {canonical_owner}; production references: "
        f"{references}"
    )


def test_retired_workflows_have_no_dynamic_entry_or_persisted_replay_reference() -> None:
    references: list[str] = []
    paths = [
        _REPOSITORY_ROOT / "pyproject.toml",
        *(
            path
            for root in _RUNTIME_REFERENCE_ROOTS
            if root.exists()
            for path in root.rglob("*")
        ),
    ]
    for path in paths:
        if (
            not path.is_file()
            or path.suffix.lower() not in _RUNTIME_REFERENCE_SUFFIXES
        ):
            continue
        content = path.read_bytes()
        encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
        text = content.decode(encoding)
        matched = sorted(
            token for token in _RETIRED_WORKFLOW_RUNTIME_TOKENS if token in text
        )
        if matched:
            references.append(
                f"{path.relative_to(_REPOSITORY_ROOT).as_posix()}: {matched}"
            )

    assert references == []


@pytest.mark.parametrize(
    "workflow_builder",
    (pytest.param(build_paper_analysis_workflow_spec, id="paper-analysis"),),
)
def test_active_workflow_has_only_exact_versioned_gate_references(workflow_builder) -> None:
    workflow = workflow_builder()

    for step in workflow.steps:
        if step.quality_gate is not None:
            GateReference.parse(step.quality_gate)


@pytest.mark.parametrize(
    "workflow_builder",
    (pytest.param(build_paper_analysis_workflow_spec, id="paper-analysis"),),
)
def test_active_workflow_does_not_verify_policy_after_a_side_effect(workflow_builder) -> None:
    workflow = workflow_builder()
    post_side_effect_gates = [
        (step.step_id, step.quality_gate)
        for step in workflow.steps
        if step.worker_type in _SIDE_EFFECT_WORKER_TYPES and step.quality_gate is not None
    ]

    assert post_side_effect_gates == []


@lru_cache(maxsize=None)
def _production_references(module_name: str, builder_name: str) -> tuple[str, ...]:
    import_target = f"business.research.workflows.{module_name}"
    references: list[str] = []
    for root in _PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if builder_name in source or import_target in source:
                references.append(path.relative_to(_REPOSITORY_ROOT).as_posix())
    return tuple(references)
