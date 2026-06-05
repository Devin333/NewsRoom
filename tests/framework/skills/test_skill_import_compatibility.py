from __future__ import annotations

import importlib


CANONICAL_MODULES = [
    "framework.skills.core.context",
    "framework.skills.core.errors",
    "framework.skills.core.io",
    "framework.skills.core.manifest",
    "framework.skills.core.metadata",
    "framework.skills.core.result",
    "framework.skills.evaluation.evaluator",
    "framework.skills.package",
    "framework.skills.package.registry",
    "framework.skills.package.scanner",
    "framework.skills.package.validator",
    "framework.skills.quality",
    "framework.skills.quality.gates",
    "framework.skills.runtime.executor",
    "framework.skills.runtime.prompt",
    "framework.skills.runtime.runner",
    "framework.skills.tracing.trace",
    "framework.skills.validation.schema",
]


def test_canonical_skill_module_paths_are_importable() -> None:
    for module_name in CANONICAL_MODULES:
        assert importlib.import_module(module_name)


def test_new_subpackage_imports_match_root_exports() -> None:
    import framework.skills as root
    from framework.skills.core.context import SkillRunContext
    from framework.skills.package.loader import SkillPackageLoader
    from framework.skills.quality.gates import SkillQualityGateResult
    from framework.skills.runtime.runner import SkillRunner
    from framework.skills.tracing.trace import SkillTraceRecorder
    from framework.skills.validation.schema import SkillSchemaValidator

    assert root.SkillRunContext is SkillRunContext
    assert root.SkillPackageLoader is SkillPackageLoader
    assert root.SkillQualityGateResult is SkillQualityGateResult
    assert root.SkillRunner is SkillRunner
    assert root.SkillTraceRecorder is SkillTraceRecorder
    assert root.SkillSchemaValidator is SkillSchemaValidator


def test_root_exports_match_canonical_objects() -> None:
    from framework import skills
    from framework.skills.core.context import SkillRunContext as CanonicalSkillRunContext
    from framework.skills.core.errors import SkillPackageError as CanonicalSkillPackageError
    from framework.skills.core.io import SkillOutput as CanonicalSkillOutput
    from framework.skills.core.manifest import SkillManifest as CanonicalSkillManifest
    from framework.skills.core.metadata import SkillMetadata as CanonicalSkillMetadata
    from framework.skills.core.result import SkillResult as CanonicalSkillResult
    from framework.skills.evaluation.evaluator import SkillEvaluator as CanonicalSkillEvaluator
    from framework.skills.package.registry import SkillRegistry as CanonicalSkillRegistry
    from framework.skills.package.scanner import SkillScanner as CanonicalSkillScanner
    from framework.skills.package.validator import SkillPackageValidator as CanonicalSkillPackageValidator
    from framework.skills.runtime.executor import MockSkillExecutor as CanonicalMockSkillExecutor
    from framework.skills.runtime.prompt import SkillPromptBuilder as CanonicalSkillPromptBuilder
    from framework.skills.runtime.runner import SkillRunner as CanonicalSkillRunner
    from framework.skills.tracing.trace import SkillTraceRecorder as CanonicalSkillTraceRecorder
    from framework.skills.validation.schema import SkillSchemaValidator as CanonicalSkillSchemaValidator

    assert skills.SkillRunContext is CanonicalSkillRunContext
    assert skills.SkillPackageError is CanonicalSkillPackageError
    assert skills.SkillOutput is CanonicalSkillOutput
    assert skills.SkillManifest is CanonicalSkillManifest
    assert skills.SkillMetadata is CanonicalSkillMetadata
    assert skills.SkillResult is CanonicalSkillResult
    assert skills.SkillEvaluator is CanonicalSkillEvaluator
    assert skills.MockSkillExecutor is CanonicalMockSkillExecutor
    assert skills.SkillPromptBuilder is CanonicalSkillPromptBuilder
    assert skills.SkillRegistry is CanonicalSkillRegistry
    assert skills.SkillRunner is CanonicalSkillRunner
    assert skills.SkillScanner is CanonicalSkillScanner
    assert skills.SkillSchemaValidator is CanonicalSkillSchemaValidator
    assert skills.SkillTraceRecorder is CanonicalSkillTraceRecorder
    assert skills.SkillPackageValidator is CanonicalSkillPackageValidator


def test_package_and_quality_packages_export_canonical_objects() -> None:
    from framework.skills.package import SkillPackage, SkillPackageLoader
    from framework.skills.package.loader import SkillPackage as CanonicalSkillPackage
    from framework.skills.package.loader import SkillPackageLoader as CanonicalSkillPackageLoader
    from framework.skills.quality import SkillQualityGateResult, SkillQualityGateRunner
    from framework.skills.quality.gates import SkillQualityGateResult as CanonicalSkillQualityGateResult
    from framework.skills.quality.gates import SkillQualityGateRunner as CanonicalSkillQualityGateRunner

    assert SkillPackage is CanonicalSkillPackage
    assert SkillPackageLoader is CanonicalSkillPackageLoader
    assert SkillQualityGateResult is CanonicalSkillQualityGateResult
    assert SkillQualityGateRunner is CanonicalSkillQualityGateRunner
