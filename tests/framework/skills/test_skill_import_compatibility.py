from __future__ import annotations

import importlib


LEGACY_MODULES = [
    "framework.skills.runner",
    "framework.skills.executor",
    "framework.skills.prompt",
    "framework.skills.schema",
    "framework.skills.package",
    "framework.skills.registry",
    "framework.skills.scanner",
    "framework.skills.validator",
    "framework.skills.quality",
    "framework.skills.evaluator",
    "framework.skills.trace",
    "framework.skills.context",
    "framework.skills.errors",
    "framework.skills.io",
    "framework.skills.metadata",
    "framework.skills.manifest",
    "framework.skills.result",
]


def test_all_legacy_skill_module_paths_remain_importable() -> None:
    for module_name in LEGACY_MODULES:
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


def test_legacy_flat_modules_reexport_canonical_objects() -> None:
    from framework.skills.context import SkillRunContext
    from framework.skills.core.context import SkillRunContext as CanonicalSkillRunContext
    from framework.skills.core.errors import SkillPackageError as CanonicalSkillPackageError
    from framework.skills.core.io import SkillOutput as CanonicalSkillOutput
    from framework.skills.core.manifest import SkillManifest as CanonicalSkillManifest
    from framework.skills.core.metadata import SkillMetadata as CanonicalSkillMetadata
    from framework.skills.core.result import SkillResult as CanonicalSkillResult
    from framework.skills.errors import SkillPackageError
    from framework.skills.evaluation.evaluator import SkillEvaluator as CanonicalSkillEvaluator
    from framework.skills.evaluator import SkillEvaluator
    from framework.skills.executor import MockSkillExecutor
    from framework.skills.io import SkillOutput
    from framework.skills.manifest import SkillManifest
    from framework.skills.metadata import SkillMetadata
    from framework.skills.package.registry import SkillRegistry as CanonicalSkillRegistry
    from framework.skills.package.scanner import SkillScanner as CanonicalSkillScanner
    from framework.skills.package.validator import SkillPackageValidator as CanonicalSkillPackageValidator
    from framework.skills.prompt import SkillPromptBuilder
    from framework.skills.registry import SkillRegistry
    from framework.skills.result import SkillResult
    from framework.skills.runner import SkillRunner
    from framework.skills.runtime.executor import MockSkillExecutor as CanonicalMockSkillExecutor
    from framework.skills.runtime.prompt import SkillPromptBuilder as CanonicalSkillPromptBuilder
    from framework.skills.runtime.runner import SkillRunner as CanonicalSkillRunner
    from framework.skills.scanner import SkillScanner
    from framework.skills.schema import SkillSchemaValidator
    from framework.skills.trace import SkillTraceRecorder
    from framework.skills.tracing.trace import SkillTraceRecorder as CanonicalSkillTraceRecorder
    from framework.skills.validation.schema import SkillSchemaValidator as CanonicalSkillSchemaValidator
    from framework.skills.validator import SkillPackageValidator

    assert SkillRunContext is CanonicalSkillRunContext
    assert SkillPackageError is CanonicalSkillPackageError
    assert SkillOutput is CanonicalSkillOutput
    assert SkillManifest is CanonicalSkillManifest
    assert SkillMetadata is CanonicalSkillMetadata
    assert SkillResult is CanonicalSkillResult
    assert SkillEvaluator is CanonicalSkillEvaluator
    assert MockSkillExecutor is CanonicalMockSkillExecutor
    assert SkillPromptBuilder is CanonicalSkillPromptBuilder
    assert SkillRegistry is CanonicalSkillRegistry
    assert SkillRunner is CanonicalSkillRunner
    assert SkillScanner is CanonicalSkillScanner
    assert SkillSchemaValidator is CanonicalSkillSchemaValidator
    assert SkillTraceRecorder is CanonicalSkillTraceRecorder
    assert SkillPackageValidator is CanonicalSkillPackageValidator


def test_legacy_package_and_quality_paths_remain_importable() -> None:
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
