from __future__ import annotations

import pytest

from interfaces.composition.research_errors import (
    ResearchCapability,
    ResearchCompositionError,
    ResearchConfigurationError,
    ResearchRemediation,
    ResearchRuntimeUnavailableError,
)


def test_composition_error_exposes_only_normalized_public_contract() -> None:
    error = ResearchCompositionError(
        (
            "research.llm.credential",
            "RESEARCH.LLM.CREDENTIAL",
            "research.rag.vector_backend",
        ),
        remediation=ResearchRemediation.RESTORE_REQUIRED_CAPABILITY,
        retryable=True,
    )

    assert error.capabilities == (
        "research.llm.credential",
        "research.rag.vector_backend",
    )
    assert error.error_code == "research_composition_failed"
    assert error.remediation_code == "restore_research_runtime_capability"
    assert error.retryable is True
    assert error.to_public_dict() == {
        "code": "research_composition_failed",
        "message": str(error),
        "capabilities": [
            "research.llm.credential",
            "research.rag.vector_backend",
        ],
        "remediation": {
            "code": "restore_research_runtime_capability",
            "message": "Restore the named Research capability and retry the request.",
        },
        "retryable": True,
    }
    assert ResearchCapability.LLM_CREDENTIAL.value == "research.llm.credential"
    assert ResearchCapability.EVENT_LOG.value == "research.event_log"


def test_configuration_error_has_stable_sanitized_contract() -> None:
    error = ResearchConfigurationError(("research.parser.timeout",))

    assert error.error_code == "research_configuration_invalid"
    assert error.capabilities == ("research.parser.timeout",)
    assert error.retryable is False
    assert error.remediation_code == "review_research_runtime_configuration"
    assert error.to_public_dict()["code"] == "research_configuration_invalid"


def test_unavailable_error_has_stable_sanitized_contract() -> None:
    error = ResearchRuntimeUnavailableError(
        (ResearchCapability.LLM_CREDENTIAL,),
        remediation=ResearchRemediation.CONFIGURE_LLM_CREDENTIAL,
    )

    assert error.error_code == "research_runtime_unavailable"
    assert error.capabilities == ("research.llm.credential",)
    assert error.retryable is False
    assert error.remediation_code == "configure_research_llm_credential"
    assert error.to_public_dict()["remediation"] == {
        "code": "configure_research_llm_credential",
        "message": (
            "Provide the configured Research LLM credential through deployment secret "
            "management."
        ),
    }


@pytest.mark.parametrize(
    "capabilities",
    [
        (),
        ("",),
        "research.llm.credential",
        ("research.llm.credential secret-value",),
        ("research.llm.$credential",),
        ("sk-private-value",),
        ("x" * 129,),
    ],
)
def test_error_rejects_unsafe_capability_names_without_echoing_them(
    capabilities: tuple[str, ...] | str,
) -> None:
    raw = capabilities if isinstance(capabilities, str) else "|".join(capabilities)

    with pytest.raises(ValueError) as exc_info:
        ResearchCompositionError(capabilities)

    assert raw not in str(exc_info.value) or not raw


def test_error_rejects_untyped_remediation_without_echoing_value() -> None:
    secret = "sk-should-never-appear"

    with pytest.raises(TypeError) as exc_info:
        ResearchCompositionError(  # type: ignore[arg-type]
            ("research.llm",),
            remediation=secret,
        )

    assert secret not in str(exc_info.value)
