from __future__ import annotations

from pathlib import Path

from framework.llm.models.response import LLMResponse

from business.research.application.visual_chunk_describer import (
    OpenAICompatibleVisualChunkDescriber,
    VisualChunkDescriptionConfig,
)
from business.research.document.models import PaperChunk


class _FakeVisionClient:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            content="The figure shows an encoder-decoder architecture with skip connections.",
            model="fake-vision",
        )


def test_visual_describer_enriches_image_backed_figure_chunk(tmp_path: Path) -> None:
    image = tmp_path / "p1" / "figures" / "arch.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-bytes")
    client = _FakeVisionClient()
    describer = OpenAICompatibleVisualChunkDescriber(
        VisualChunkDescriptionConfig(
            enabled=True,
            base_url="https://example.test/v1",
            model="gpt-5.4-mini",
            image_root=tmp_path,
        ),
        client=client,  # type: ignore[arg-type]
    )
    chunk = PaperChunk(
        chunk_id="fig-1",
        paper_id="p1",
        parse_source="nougat",
        chunk_type="figure",
        has_figure=True,
        figure_id="fig1",
        content="[Figure fig1]\nCaption:\nU-Net architecture.",
        metadata={"image_ref": "p1/figures/arch.png"},
    )

    [updated] = describer.describe_chunks([chunk])

    assert updated.metadata["visual_description"].startswith("The figure shows")
    assert updated.metadata["visual_description_status"] == "ok"
    assert updated.metadata["visual_description_generated_at"]
    assert updated.metadata["visual_description_model"] == "gpt-5.4-mini"
    assert updated.metadata["visual_description_source"] == "openai-compatible-vision"
    assert "Visual Description:" in updated.content
    assert "encoder-decoder architecture" in updated.content
    message = client.requests[0].messages[0]
    assert isinstance(message["content"], list)
    assert message["content"][1]["type"] == "image_url"


def test_visual_describer_skips_missing_images() -> None:
    describer = OpenAICompatibleVisualChunkDescriber(
        VisualChunkDescriptionConfig(
            enabled=True,
            base_url="https://example.test/v1",
            model="gpt-5.4-mini",
        ),
        client=_FakeVisionClient(),  # type: ignore[arg-type]
    )
    chunk = PaperChunk(
        chunk_id="fig-1",
        paper_id="p1",
        parse_source="nougat",
        chunk_type="figure",
        content="[Figure fig1]\nCaption:\nMissing image.",
        metadata={"image_ref": "missing.png"},
    )

    [updated] = describer.describe_chunks([chunk])

    assert updated.metadata["visual_description_skipped"] is True
    assert updated.metadata["visual_description_skip_reason"] == "image_missing"
    assert updated.metadata["visual_description_status"] == "missing_image"
    assert "visual_description" not in updated.metadata
