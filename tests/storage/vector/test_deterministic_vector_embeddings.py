from storage.vector import DeterministicEmbeddingModel, FakeEmbeddingAdapter


def test_deterministic_embedding_is_stable_and_normalized() -> None:
    model = DeterministicEmbeddingModel(dimension=16)

    first = model.embed_text("Agent runtime memory")
    second = model.embed_text("Agent runtime memory")

    assert first == second
    assert len(first) == 16
    assert round(sum(value * value for value in first), 6) == 1.0


def test_empty_embedding_returns_zero_vector() -> None:
    model = DeterministicEmbeddingModel(dimension=4)

    assert model.embed_text("") == [0.0, 0.0, 0.0, 0.0]


def test_fake_embedding_adapter_is_stable_test_adapter() -> None:
    model = FakeEmbeddingAdapter(dimension=8)

    assert model.embed_text("storage memory") == model.embed_text("storage memory")
    assert len(model.embed_text("storage memory")) == 8
