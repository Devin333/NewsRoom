from core.framework.tools import (
    EnvironmentSecretProvider,
    MappingSecretProvider,
    ToolCall,
    ToolBatchExecutor,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    ToolTestCase,
    ToolTestRunner,
)


def test_tool_definition_exports_required_secret_names_without_values() -> None:
    definition = ToolDefinition(
        name="github.search",
        required_secret_names=["GITHUB_TOKEN"],
    )

    payload = definition.to_dict()

    assert payload["required_secret_names"] == ["GITHUB_TOKEN"]
    assert "github-secret-value" not in str(payload)


def test_mapping_secret_provider_returns_configured_secret() -> None:
    provider = MappingSecretProvider({"GITHUB_TOKEN": "github-secret-value"})

    assert provider.get_secret("GITHUB_TOKEN") == "github-secret-value"
    assert provider.get_secret("MISSING") is None


def test_environment_secret_provider_reads_supplied_environment_mapping() -> None:
    provider = EnvironmentSecretProvider({"GITHUB_TOKEN": "github-secret-value"})

    assert provider.get_secret("GITHUB_TOKEN") == "github-secret-value"


def test_tool_executor_injects_required_secrets_without_mutating_tool_call() -> None:
    seen_arguments: dict = {}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="github.search",
            input_schema={"required": ["query"]},
            required_secret_names=["GITHUB_TOKEN"],
        ),
        lambda args: seen_arguments.update(args)
        or {"used_credential": args["_secrets"]["GITHUB_TOKEN"] == "github-secret-value"},
    )
    call = ToolCall(tool_name="github.search", arguments={"query": "agent runtime"})
    executor = ToolExecutor(
        registry,
        secret_provider=MappingSecretProvider({"GITHUB_TOKEN": "github-secret-value"}),
    )

    observation = executor.execute(call, ToolPolicy(allowed_tools=["github.search"]))

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"used_credential": True}
    assert seen_arguments["_secrets"]["GITHUB_TOKEN"] == "github-secret-value"
    assert "_secrets" not in call.arguments
    assert "_secrets" not in observation.call.arguments


def test_tool_executor_fails_missing_required_secret_before_invocation() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="github.search",
            input_schema={"required": ["query"]},
            required_secret_names=["GITHUB_TOKEN"],
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry, secret_provider=MappingSecretProvider({}))

    observation = executor.execute(
        ToolCall(tool_name="github.search", arguments={"query": "agent runtime"}),
        ToolPolicy(allowed_tools=["github.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolSecretError"
    assert calls["count"] == 0


def test_tool_executor_rejects_caller_supplied_runtime_secrets_argument() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="github.search", input_schema={"required": ["query"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="github.search",
            arguments={"query": "agent runtime", "_secrets": {"GITHUB_TOKEN": "spoofed"}},
        ),
        ToolPolicy(allowed_tools=["github.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolRuntimeError"
    assert "reserved tool argument" in (observation.result.error_message or "")
    assert calls["count"] == 0


def test_tool_test_runner_uses_secret_provider() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="github.search",
            input_schema={"required": ["query"]},
            required_secret_names=["GITHUB_TOKEN"],
        ),
        lambda args: {"has_credential": "GITHUB_TOKEN" in args["_secrets"]},
    )
    runner = ToolTestRunner(
        registry,
        secret_provider=MappingSecretProvider({"GITHUB_TOKEN": "github-secret-value"}),
    )

    report = runner.run_case(
        ToolTestCase(
            name="secret tool",
            call=ToolCall(tool_name="github.search", arguments={"query": "agent runtime"}),
            policy=ToolPolicy(allowed_tools=["github.search"]),
        )
    )

    assert report.passed is True
    assert report.observation.result.output == {"has_credential": True}


def test_tool_batch_executor_uses_secret_provider() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="github.search",
            input_schema={"required": ["query"]},
            required_secret_names=["GITHUB_TOKEN"],
            concurrency_safe=True,
        ),
        lambda args: {"has_credential": "GITHUB_TOKEN" in args["_secrets"]},
    )
    batch_executor = ToolBatchExecutor(
        registry,
        secret_provider=MappingSecretProvider({"GITHUB_TOKEN": "github-secret-value"}),
    )

    observations = batch_executor.execute_batch(
        [ToolCall(tool_name="github.search", arguments={"query": "agent runtime"})],
        ToolPolicy(allowed_tools=["github.search"]),
    )

    assert observations[0].status == ToolStatus.SUCCEEDED
    assert observations[0].result.output == {"has_credential": True}
