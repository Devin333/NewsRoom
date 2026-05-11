from core.framework.llm import ModelCapabilities


def test_model_capabilities_default_to_unsupported() -> None:
    capabilities = ModelCapabilities()

    assert capabilities.supports("json_mode") is False
    assert capabilities.supports("tool_calling") is False
    assert capabilities.missing(("json_mode", "tool_calling")) == ("json_mode", "tool_calling")


def test_model_capabilities_support_aliases() -> None:
    capabilities = ModelCapabilities(
        supports_json_mode=True,
        supports_tool_calling=True,
        supports_structured_output=True,
    )

    assert capabilities.supports("json") is True
    assert capabilities.supports("tools") is True
    assert capabilities.supports("supports_structured_output") is True
    assert capabilities.missing(("json_mode", "tools", "structured_output")) == ()
