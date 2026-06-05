from __future__ import annotations


def test_framework_root_exports_stable_compatibility_surface() -> None:
    import framework

    assert {"RunResult", "WorkflowRunner", "shared", "specs"}.issubset(set(framework.__all__))
    assert len(framework.__all__) <= 8


def test_workflow_root_exports_stable_compatibility_names() -> None:
    import framework.workflow as workflow

    required_names = {
        "WorkflowRunner",
        "WorkflowExecutor",
        "WorkflowResult",
        "StepOutcome",
        "SkillStepSpec",
        "build_default_step_runner_registry",
    }

    assert required_names.issubset(set(workflow.__all__))
    assert len(workflow.__all__) <= 306


def test_workflow_skill_step_spec_is_compatibility_reexport() -> None:
    from framework.specs import SkillStepSpec as CanonicalSkillStepSpec
    from framework.workflow.specs import SkillStepSpec as PackageSkillStepSpec
    from framework.specs.skill_step import SkillStepSpec as ModuleSkillStepSpec

    assert PackageSkillStepSpec is CanonicalSkillStepSpec
    assert ModuleSkillStepSpec is CanonicalSkillStepSpec
