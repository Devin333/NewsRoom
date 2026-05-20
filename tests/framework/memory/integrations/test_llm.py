from framework.memory import LLMMemoryContextInjector, MemoryContextBlock


def test_llm_context_injector_prepends_system_message() -> None:
    messages = [{"role": "user", "content": "hello"}]
    context = MemoryContextBlock(content="memory", token_estimate=1, memory_ids=["mem-1"])

    injected = LLMMemoryContextInjector().inject(messages=messages, context=context)

    assert injected[0] == {"role": "system", "content": "memory"}
    assert injected[1:] == messages
