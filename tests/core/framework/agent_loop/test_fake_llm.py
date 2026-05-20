from framework.llm import FakeLLMClient, LLMRequest


def test_fake_llm_returns_scripted_responses_and_usage() -> None:
    client = FakeLLMClient(['{"action_type":"final_output","output":{"answer":"ok"}}'])

    response = client.complete(LLMRequest(messages=[{"role": "user", "content": "go"}]))

    assert response.content == '{"action_type":"final_output","output":{"answer":"ok"}}'
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 8
    assert response.usage.total_tokens == 20
    assert client.call_count == 1
    assert client.requests[0].messages[0]["content"] == "go"

