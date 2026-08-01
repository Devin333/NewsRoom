from __future__ import annotations

from framework.harness.skills.evolution.models import FORBIDDEN_SKILL_CANDIDATE_KEYS
from framework.harness.workers.result import FORBIDDEN_WORKER_RESULT_KEYS
from tests.architecture._helpers import PROJECT_ROOT, forbidden_imports, token_violations


SKILL_EVOLUTION_ROOT = PROJECT_ROOT / "framework" / "harness" / "skills" / "evolution"
HARNESS_ROOT = PROJECT_ROOT / "framework" / "harness"
SKILL_BYPASS_TOKENS = (
    "auto_promote",
    "self_modify_production_skill",
    "llm_decides_promotion",
    "disable_quality_gate",
    "skip_eval",
)
ALLOWED_BYPASS_GUARDRAIL_REFERENCES = {
    "framework/harness/workers/result.py: auto_promote",
    "framework/harness/workers/result.py: skip_eval",
    "framework/harness/skills/evolution/models.py: auto_promote",
    "framework/harness/skills/evolution/models.py: skip_eval",
}


def test_skill_evolution_does_not_import_outer_layers() -> None:
    assert forbidden_imports(SKILL_EVOLUTION_ROOT, ("business", "interfaces", "infrastructure")) == []


def test_skill_evolution_bypass_tokens_only_appear_in_guardrails() -> None:
    violations = [
        violation
        for violation in token_violations(HARNESS_ROOT, SKILL_BYPASS_TOKENS)
        if violation not in ALLOWED_BYPASS_GUARDRAIL_REFERENCES
    ]

    assert violations == []
    assert {"auto_promote", "skip_eval"} <= FORBIDDEN_WORKER_RESULT_KEYS
    assert {"auto_promote", "skip_eval"} <= FORBIDDEN_SKILL_CANDIDATE_KEYS


def test_skill_evolution_models_require_harness_promotion_authority() -> None:
    model_source = (SKILL_EVOLUTION_ROOT / "models.py").read_text(encoding="utf-8")
    authority_source = (SKILL_EVOLUTION_ROOT / "authority.py").read_text(encoding="utf-8")
    release_source = (SKILL_EVOLUTION_ROOT / "release.py").read_text(encoding="utf-8")

    assert 'decided_by: str = "harness"' in model_source
    assert 'decided_by=\'harness\'' in model_source
    assert "release_authorization_ref" in model_source
    assert "HarnessSideEffectStorePort" in authority_source
    assert "skill_release_side_effect_decision_missing" in authority_source
    assert "authorization_ref = release.release_authorization_ref" in release_source
    assert "self.authority_resolver.resolve(authorization_ref)" in release_source
