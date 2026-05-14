from core.framework.llm import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    REDACTED_VALUE,
    TokenUsage,
    redact_sensitive_values,
)


def test_llm_request_to_dict_redacts_by_default() -> None:
    secret = _secret()
    bearer = "Bearer " + "llm-redaction-token"
    request = LLMRequest(
        messages=[
            {
                "role": "user",
                "content": f"Summarize this private token: {secret}",
            }
        ],
        tools=[{"name": "memory.search", "metadata": {"api_key": secret}}],
        metadata={"authorization": bearer},
    )

    payload = request.to_dict()

    assert secret not in str(payload)
    assert "llm-redaction-token" not in str(payload)
    assert payload["messages"][0]["content"] == f"Summarize this private token: {REDACTED_VALUE}"
    assert payload["tools"][0]["metadata"]["api_key"] == REDACTED_VALUE
    assert payload["metadata"]["authorization"] == REDACTED_VALUE


def test_llm_request_to_dict_can_return_raw_snapshot() -> None:
    secret = _secret()
    request = LLMRequest(messages=[{"role": "user", "content": secret}])

    payload = request.to_dict(redact=False)

    assert payload["messages"][0]["content"] == secret


def test_llm_response_to_dict_redacts_content_and_metadata_by_default() -> None:
    secret = _secret()
    response = LLMResponse(
        content=f"model echoed {secret}",
        usage=TokenUsage(input_tokens=3, output_tokens=5),
        metadata={"provider": "test", "session_token": secret},
        structured_output={"leaked": secret},
        tool_calls=[
            LLMToolCall(
                tool_call_id="call_1",
                tool_name="memory.search",
                arguments={"token": secret},
                raw_arguments="{\"token\":\"" + secret + "\"}",
            )
        ],
    )

    payload = response.to_dict()

    assert secret not in str(payload)
    assert payload["content"] == f"model echoed {REDACTED_VALUE}"
    assert payload["metadata"]["session_token"] == REDACTED_VALUE
    assert payload["structured_output"]["leaked"] == REDACTED_VALUE
    assert payload["tool_calls"][0]["arguments"]["token"] == REDACTED_VALUE
    assert secret not in payload["tool_calls"][0]["raw_arguments"]
    assert payload["usage"]["input_tokens"] == 3
    assert payload["usage"]["output_tokens"] == 5
    assert payload["usage"]["total_tokens"] == 8


def test_llm_provider_error_to_dict_redacts_message() -> None:
    secret = _secret()
    error = LLMProviderError(
        f"provider returned raw credential {secret}",
        provider="test",
        error_type="provider_client_error",
        retryable=False,
        status_code=400,
        attempts=1,
    )

    payload = error.to_dict()

    assert secret not in str(payload)
    assert payload["message"] == f"provider returned raw credential {REDACTED_VALUE}"
    assert payload["provider"] == "test"
    assert payload["model"] is None
    assert payload["deployment_id"] is None
    assert payload["error_type"] == "provider_client_error"
    assert payload["error_category"] == "provider_client_error"
    assert payload["retryable"] is False
    assert payload["status_code"] == 400
    assert payload["attempts"] == 1


def test_redactor_masks_password_bearing_dsn_in_free_text() -> None:
    dsn = "postgresql://news_user:" + "local-password" + "@localhost/news"

    payload = redact_sensitive_values({"message": f"connect with {dsn}"})

    assert "local-password" not in payload["message"]
    assert REDACTED_VALUE in payload["message"]


def _secret() -> str:
    return "sk" + "-llm-redaction-secret"
