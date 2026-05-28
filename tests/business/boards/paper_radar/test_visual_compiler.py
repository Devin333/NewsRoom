import json
from datetime import datetime, timezone
from io import BytesIO
import tarfile

from fastapi.testclient import TestClient

from business.boards.paper_radar.visual_compiler import (
    ArxivSourcePaperCompiler,
    PaperAssetGate,
    PaperLayoutDetection,
    PaperLayoutRegion,
    PaperVisualCompilerRepository,
    PyMuPDFPaperCompiler,
    SourceFirstPaperCompiler,
)
from infrastructure.external.sources.arxiv import ArxivSourceConnector, build_arxiv_source_url, normalize_arxiv_id
from business.boards.paper_radar.visual_compiler.model_layout_provider import (
    OpenAICompatiblePaperLayoutProvider,
    build_model_layout_provider_from_env,
)
from business.boards.paper_radar.visual_compiler.models import (
    PaperAssetManifest,
    PaperBlock,
    PaperDocument,
    PaperSourceRegion,
    PaperVisualAsset,
)
from business.boards.paper_radar.visual_compiler.reviewer import HeuristicPaperDocumentReviewer
from business.boards.paper_radar.worker_handlers import PaperVisualCompileTaskHandler
from framework.workers import Task
from framework.workers.models import TaskStatus
from interfaces.api import create_app
from interfaces.services.paper_service import PapersApplicationService
from interfaces.services.paper_visual_compiler_service import PaperVisualCompilerApplicationService


def test_visual_compiler_publishes_pdf_blocks_and_keeps_ai_summary_out_of_body(tmp_path) -> None:
    service = _visual_service(tmp_path, reviewer=HeuristicPaperDocumentReviewer(verdict="pass"))

    result = service.compile_paper("visual-paper", force=True, run_id="visual-test")
    payload = service.get_document_payload("visual-paper")

    assert result.status == "compiled"
    assert payload["document"]["status"] == "compiled"
    body_text = "\n".join(block.get("text", "") for block in payload["document"]["blocks"])
    assert "Introduction" in body_text
    assert "Generated AI summary should stay outside body." not in body_text
    assert any(block["type"] == "figure" and block.get("assetId") for block in payload["document"]["blocks"])
    assert any(asset["kind"] == "page" for asset in payload["manifest"]["assets"])
    assert payload["ai"]["signals"]["abstractSnippet"] == "Generated AI summary should stay outside body."


def test_asset_gate_blocks_missing_visual_asset_file(tmp_path) -> None:
    service = _visual_service(tmp_path, reviewer=HeuristicPaperDocumentReviewer(verdict="pass"))
    result = service.compile_paper("visual-paper", force=True)
    assert result.document is not None
    assert result.manifest is not None
    visual_asset = next(asset for asset in result.manifest.assets if asset.kind == "figure")
    (service.repository.paper_dir("visual-paper") / visual_asset.fileName).unlink()

    gate_report = PaperAssetGate().validate(
        document=result.document,
        manifest=result.manifest,
        paper_dir=service.repository.paper_dir("visual-paper"),
    )

    assert gate_report["passed"] is False
    assert any(error["code"] == "asset_file_missing" for error in gate_report["errors"])


def test_visual_compiler_skips_uncaptioned_image_blocks_before_asset_gate(tmp_path) -> None:
    output_dir = tmp_path / "uncaptioned"
    draft = PyMuPDFPaperCompiler(dpi=96).compile(
        pdf_bytes=_uncaptioned_image_pdf_bytes(),
        paper={
            "id": "uncaptioned-paper",
            "title": "Uncaptioned Image Paper",
            "abstractSnippet": "This paper contains an image without a figure caption.",
        },
        output_dir=output_dir,
        source_pdf_url="https://arxiv.org/pdf/2605.00001.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    gate_report = PaperAssetGate().validate(
        document=draft.document,
        manifest=draft.manifest,
        paper_dir=output_dir,
    )

    visual_assets = [asset for asset in draft.manifest.assets if asset.kind in {"figure", "table"}]
    assert gate_report["passed"] is True
    assert visual_assets == []
    assert any(item["code"] == "uncaptioned_image_skipped" for item in draft.compile_info.diagnostics)


def test_visual_compiler_uses_model_layout_provider_for_table_and_figure_crops(tmp_path) -> None:
    output_dir = tmp_path / "model-layout"
    compiler = PyMuPDFPaperCompiler(dpi=96, layout_provider=_FakeLayoutProvider(), max_visual_assets_per_page=8)

    draft = compiler.compile(
        pdf_bytes=_layout_provider_pdf_bytes(),
        paper={
            "id": "model-layout-paper",
            "title": "Model Layout Paper",
            "abstractSnippet": "AI summary must remain outside the body.",
        },
        output_dir=output_dir,
        source_pdf_url="https://arxiv.org/pdf/2605.00002.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )
    gate_report = PaperAssetGate().validate(
        document=draft.document,
        manifest=draft.manifest,
        paper_dir=output_dir,
    )

    visual_blocks = [block for block in draft.document.blocks if block.type in {"figure", "table"}]
    equation_blocks = [block for block in draft.document.blocks if block.type == "equation"]
    assert gate_report["passed"] is True
    assert {block.type for block in visual_blocks} == {"figure", "table"}
    assert any(asset.kind == "table" and asset.metadata.get("layoutProvider") == "fake-model-layout-v1" for asset in draft.manifest.assets)
    assert any(asset.kind == "figure" and asset.metadata.get("layoutProvider") == "fake-model-layout-v1" for asset in draft.manifest.assets)
    assert not any(asset.kind == "equation" for asset in draft.manifest.assets)
    assert equation_blocks
    assert all(block.assetId is None for block in equation_blocks)
    assert all(block.source is not None for block in equation_blocks)
    assert any("y = Wx + b" in block.text for block in equation_blocks)
    assert all("Figure 1" not in block.text for block in equation_blocks)
    assert "AI summary must remain outside the body." not in "\n".join(block.text for block in draft.document.blocks)


def test_visual_compiler_prefers_model_equation_text_over_overlapping_pdf_prose(tmp_path) -> None:
    output_dir = tmp_path / "model-equation-text"
    compiler = PyMuPDFPaperCompiler(dpi=96, layout_provider=_ModelEquationTextLayoutProvider(), max_visual_assets_per_page=8)

    draft = compiler.compile(
        pdf_bytes=_model_equation_text_pdf_bytes(),
        paper={
            "id": "model-equation-paper",
            "title": "Model Equation Paper",
            "abstractSnippet": "AI summary must remain outside the body.",
        },
        output_dir=output_dir,
        source_pdf_url="https://arxiv.org/pdf/2605.00005.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    equation_blocks = [block for block in draft.document.blocks if block.type == "equation"]
    assert len(equation_blocks) == 1
    assert equation_blocks[0].text == r"q(x_t \mid x_0)=\mathcal{N}(x_t;\sqrt{\alpha_t}x_0,(1-\alpha_t)I)"
    assert equation_blocks[0].metadata.get("modelGeneratedEquationText") is True
    assert "Given a data sample" not in equation_blocks[0].text


def test_visual_compiler_keeps_visual_ocr_and_hyphenation_noise_out_of_body(tmp_path) -> None:
    output_dir = tmp_path / "clean-body"
    compiler = PyMuPDFPaperCompiler(dpi=96, layout_provider=_CleanBodyLayoutProvider(), max_visual_assets_per_page=8)

    draft = compiler.compile(
        pdf_bytes=_noisy_visual_pdf_bytes(),
        paper={
            "id": "clean-body-paper",
            "title": "Clean Body Paper",
            "abstractSnippet": "AI summary must remain outside the body.",
        },
        output_dir=output_dir,
        source_pdf_url="https://arxiv.org/pdf/2605.00003.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    body_text = "\n".join(block.text for block in draft.document.blocks if block.type == "paragraph")
    figure_blocks = [block for block in draft.document.blocks if block.type == "figure"]

    assert "approaches often encode text and reference images separately" in body_text
    assert "ap- proaches" not in body_text
    assert "Approaches" not in body_text
    assert "CLIP-T" not in body_text
    assert "Reference Image" not in body_text
    assert "Method [1] 22.6 7.0 0.486 DreamO [2] 22.1 9.6 0.372" not in body_text
    assert "1" not in {block.text for block in draft.document.blocks if block.type == "paragraph"}
    assert len(figure_blocks) == 1
    assert figure_blocks[0].caption == "Figure 1: A real multi-line figure caption from the paper."
    assert any(item["code"] == "visual_text_blocks_skipped" for item in draft.compile_info.diagnostics)


def test_visual_compiler_merges_multiple_image_blocks_for_one_caption(tmp_path) -> None:
    output_dir = tmp_path / "multi-image-figure"

    draft = PyMuPDFPaperCompiler(dpi=96).compile(
        pdf_bytes=_multi_image_figure_pdf_bytes(),
        paper={
            "id": "multi-image-paper",
            "title": "Multi Image Figure Paper",
            "abstractSnippet": "AI summary must remain outside the body.",
        },
        output_dir=output_dir,
        source_pdf_url="https://arxiv.org/pdf/2605.00004.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    figure_blocks = [block for block in draft.document.blocks if block.type == "figure"]
    figure_assets = [asset for asset in draft.manifest.assets if asset.kind == "figure"]

    assert len(figure_blocks) == 1
    assert len(figure_assets) == 1
    assert figure_blocks[0].label == "Figure 1"
    assert int(figure_assets[0].metadata.get("imageBlockCount") or 0) >= 2


def test_visual_compiler_keeps_two_column_prose_out_of_image_figure_crop(tmp_path) -> None:
    output_dir = tmp_path / "two-column-figure"

    draft = PyMuPDFPaperCompiler(dpi=96).compile(
        pdf_bytes=_two_column_image_figure_pdf_bytes(),
        paper={
            "id": "two-column-figure-paper",
            "title": "Two Column Figure Paper",
            "abstractSnippet": "AI summary must remain outside the body.",
        },
        output_dir=output_dir,
        source_pdf_url="https://arxiv.org/pdf/2605.00005.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    figure_asset = next(asset for asset in draft.manifest.assets if asset.kind == "figure")
    body_text = "\n".join(block.text for block in draft.document.blocks if block.type == "paragraph")

    assert figure_asset.source is not None
    assert figure_asset.source.bbox[0] >= 300
    assert figure_asset.source.bbox[1] >= 190
    assert figure_asset.source.bbox[2] <= 520
    assert figure_asset.source.bbox[3] <= 410
    assert "Left column prose must stay readable" in body_text
    assert "Panel prompt" not in body_text
    assert "Reference Image" not in body_text


def test_asset_gate_blocks_oversegmented_visual_labels(tmp_path) -> None:
    paper_dir = tmp_path / "oversegmented"
    assets_dir = paper_dir / "assets"
    assets_dir.mkdir(parents=True)

    blocks: list[PaperBlock] = []
    assets: list[PaperVisualAsset] = []
    for index in range(4):
        file_path = assets_dir / f"figure-{index}.png"
        file_path.write_bytes(_sample_png_bytes())
        source = PaperSourceRegion(pageNumber=1, bbox=(72.0 + index * 20, 120.0, 112.0 + index * 20, 160.0))
        asset_id = f"asset-{index}"
        assets.append(
            PaperVisualAsset(
                assetId=asset_id,
                paperId="oversegmented-paper",
                kind="figure",
                fileName=f"assets/figure-{index}.png",
                mimeType="image/png",
                width=40,
                height=40,
                checksum=_sha256(file_path.read_bytes()),
                pageNumber=1,
                label="Figure 1",
                caption="Figure 1: One figure should not be split into many cards.",
                source=source,
                blankRatio=0.0,
            )
        )
        blocks.append(
            PaperBlock(
                id=f"block-{index}",
                paperId="oversegmented-paper",
                type="figure",
                text="Figure 1: One figure should not be split into many cards.",
                pageNumber=1,
                assetId=asset_id,
                label="Figure 1",
                caption="Figure 1: One figure should not be split into many cards.",
                source=source,
            )
        )

    document = PaperDocument(
        paperId="oversegmented-paper",
        schemaVersion="paper_document_v1",
        status="needs_review",
        title="Oversegmented Paper",
        compiledAt="2026-05-28T00:00:00Z",
        sourceHash="hash",
        paper={},
        outline=(),
        blocks=tuple(blocks),
    )
    manifest = PaperAssetManifest(
        paperId="oversegmented-paper",
        schemaVersion="paper_document_v1",
        createdAt="2026-05-28T00:00:00Z",
        sourceHash="hash",
        assets=tuple(assets),
    )

    gate_report = PaperAssetGate().validate(document=document, manifest=manifest, paper_dir=paper_dir)

    assert gate_report["passed"] is False
    assert any(error["code"] == "visual_block_label_repeated" for error in gate_report["errors"])


def test_model_layout_provider_env_factory_requires_explicit_enablement() -> None:
    assert build_model_layout_provider_from_env({}) is None

    provider = build_model_layout_provider_from_env(
        {
            "NEWSROOM_PAPER_PDF_PARSE_MODEL_ENABLED": "true",
            "NEWSROOM_PAPER_PDF_PARSE_MODEL_BASE_URL": "https://model.example/v1",
            "NEWSROOM_PAPER_PDF_PARSE_MODEL_API_KEY": "test-key",
            "NEWSROOM_PAPER_PDF_PARSE_MODEL": "vision-layout-model",
        }
    )

    assert isinstance(provider, OpenAICompatiblePaperLayoutProvider)


def test_arxiv_source_compiler_uses_tex_body_equations_and_source_assets(tmp_path) -> None:
    compiler = ArxivSourcePaperCompiler(source_fetcher=lambda _arxiv_id, _max_bytes: _sample_arxiv_source_tarball())

    attempt = compiler.try_compile(
        paper={
            "id": "arxiv-source-paper",
            "slug": "arxiv-source-paper",
            "title": "Fallback Title",
            "abstractSnippet": "Generated AI summary should stay outside body.",
            "arxivId": "2605.12345v1",
            "pdfUrl": "https://arxiv.org/pdf/2605.12345v1.pdf",
        },
        output_dir=tmp_path / "arxiv-source",
        source_pdf_url="https://arxiv.org/pdf/2605.12345v1.pdf",
        pdf_bytes=_sample_pdf_bytes(),
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    assert attempt.available is True
    assert attempt.draft is not None
    draft = attempt.draft
    gate_report = PaperAssetGate().validate(
        document=draft.document,
        manifest=draft.manifest,
        paper_dir=tmp_path / "arxiv-source",
    )
    body_text = "\n".join(block.text for block in draft.document.blocks)
    equation_blocks = [block for block in draft.document.blocks if block.type == "equation"]
    figure_blocks = [block for block in draft.document.blocks if block.type == "figure"]
    table_blocks = [block for block in draft.document.blocks if block.type == "table"]

    assert gate_report["passed"] is True
    assert draft.compile_info.provider == "arxiv-source-tex-v1"
    assert draft.document.title == "Source First Paper"
    assert "Introduction from TeX source" in body_text
    assert "Generated AI summary should stay outside body." not in body_text
    assert len(equation_blocks) == 1
    assert equation_blocks[0].assetId is None
    assert r"q(\mathbf{x}_t\mid\mathbf{x}_0)" in equation_blocks[0].text
    assert figure_blocks and figure_blocks[0].assetId
    assert table_blocks and table_blocks[0].assetId
    assert any(asset.kind == "figure" and asset.metadata.get("sourceFile") == "img/figure.pdf" for asset in draft.manifest.assets)
    assert any(asset.kind == "table" and asset.metadata.get("sourceKind") == "tex-table-rendered-text" for asset in draft.manifest.assets)


def test_source_first_compiler_falls_back_to_pdf_when_arxiv_source_unavailable(tmp_path) -> None:
    source_compiler = ArxivSourcePaperCompiler(source_fetcher=lambda _arxiv_id, _max_bytes: None)
    fallback_compiler = PyMuPDFPaperCompiler(dpi=96)
    compiler = SourceFirstPaperCompiler(source_compiler=source_compiler, fallback_compiler=fallback_compiler)

    draft = compiler.compile(
        pdf_bytes=_sample_pdf_bytes(),
        paper={
            "id": "source-fallback-paper",
            "title": "Source Fallback Paper",
            "abstractSnippet": "AI summary must remain outside the body.",
            "arxivId": "2605.54321v1",
        },
        output_dir=tmp_path / "source-fallback",
        source_pdf_url="https://arxiv.org/pdf/2605.54321v1.pdf",
        started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    assert draft.compile_info.provider.startswith("arxiv-source-tex-v1+fallback:")
    assert any(item["code"] == "source_first_fallback_used" for item in draft.compile_info.diagnostics)
    assert any(block.type == "figure" for block in draft.document.blocks)


def test_arxiv_source_connector_builds_official_source_url_and_normalizes_ids() -> None:
    assert normalize_arxiv_id("https://arxiv.org/pdf/2605.26111v1.pdf") == "2605.26111v1"
    assert build_arxiv_source_url("2605.26111v1") == "https://arxiv.org/e-print/2605.26111v1"
    assert isinstance(ArxivSourceConnector(), ArxivSourceConnector)


def test_visual_compiler_review_failure_blocks_document_payload(tmp_path) -> None:
    service = _visual_service(tmp_path, reviewer=HeuristicPaperDocumentReviewer(verdict="fail"))

    result = service.compile_paper("visual-paper", force=True)
    payload = service.get_document_payload("visual-paper")

    assert result.status == "review_failed"
    assert payload["document"] is None
    assert payload["manifest"] is None
    assert payload["status"]["reviewReport"]["verdict"] == "fail"


def test_visual_compile_worker_handler_uses_same_compile_path(tmp_path) -> None:
    service = _visual_service(tmp_path, reviewer=HeuristicPaperDocumentReviewer(verdict="pass"))
    handler = PaperVisualCompileTaskHandler(service)

    result = handler.handle(Task(task_type=handler.task_type, payload={"paper_id": "visual-paper", "force": True}))

    assert result.success is True
    assert result.status == TaskStatus.SUCCEEDED
    assert result.output["status"] == "compiled"
    assert service.get_compile_status("visual-paper").status == "compiled"


def test_paper_document_api_blocks_uncompiled_body_and_serves_compiled_assets(tmp_path) -> None:
    service = _visual_service(tmp_path, reviewer=HeuristicPaperDocumentReviewer(verdict="pass"))
    papers_service = service.papers_service
    client = TestClient(
        create_app(
            papers_service_factory=lambda: papers_service,
            paper_visual_compiler_service_factory=lambda: service,
            worker_service_factory=lambda: _FakeWorkerService(),
            audit_emitter_factory=None,
        )
    )

    uncompiled = client.get("/api/v1/papers/visual-paper/document")
    assert uncompiled.status_code == 200
    assert uncompiled.json()["data"]["status"]["status"] == "queued"
    assert uncompiled.json()["data"]["document"] is None

    compile_response = client.post("/api/v1/papers/visual-paper/compile", json={"force": True, "runId": "api-run"})
    assert compile_response.status_code == 200
    assert compile_response.json()["data"]["enqueued"]["task_type"] == "papers.visual_compile"

    service.compile_paper("visual-paper", force=True)
    compiled = client.get("/api/v1/papers/visual-paper/document")
    document_payload = compiled.json()["data"]
    visual_asset = next(asset for asset in document_payload["manifest"]["assets"] if asset["kind"] == "figure")
    source = next(block["source"] for block in document_payload["document"]["blocks"] if block["type"] == "figure")

    assert compiled.status_code == 200
    assert document_payload["document"]["status"] == "compiled"
    asset_response = client.get(f"/api/v1/papers/visual-paper/assets/{visual_asset['assetId']}")
    assert asset_response.status_code == 200
    assert asset_response.headers["content-type"] == "image/png"
    bbox = source["bbox"]
    preview_response = client.get(
        "/api/v1/papers/visual-paper/source-preview",
        params={"page": source["pageNumber"], "bbox": f"{bbox['x0']},{bbox['y0']},{bbox['x1']},{bbox['y1']}"},
    )
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "image/png"


def _visual_service(tmp_path, *, reviewer) -> PaperVisualCompilerApplicationService:
    cache_path = tmp_path / "papers.json"
    cache_path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "id": "visual-paper",
                        "slug": "visual-paper",
                        "title": "Visual Compiler Paper",
                        "abstractSnippet": "Generated AI summary should stay outside body.",
                        "authors": ["A"],
                        "publishedAt": "2026-05-24T00:00:00Z",
                        "venue": "arXiv",
                        "tags": ["cs.AI"],
                        "paperUrl": "https://arxiv.org/abs/2605.99999",
                        "pdfUrl": "https://arxiv.org/pdf/2605.99999.pdf",
                        "isPublished": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    papers_service = PapersApplicationService(papers_data_path=cache_path)
    return PaperVisualCompilerApplicationService(
        papers_service=papers_service,
        repository=PaperVisualCompilerRepository(tmp_path / "visual-compiler"),
        compiler=PyMuPDFPaperCompiler(),
        reviewer=reviewer,
        pdf_fetcher=lambda _url, _max_bytes: _sample_pdf_bytes(),
        clock=lambda: datetime(2026, 5, 28, tzinfo=timezone.utc),
    )


def _sample_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Visual Compiler Paper", fontsize=20)
    page.insert_text((72, 118), "Introduction", fontsize=16)
    page.insert_textbox(
        fitz.Rect(72, 142, 540, 220),
        "This paragraph is the real paper body extracted from the PDF compiler. It describes a method.",
        fontsize=11,
    )
    figure_rect = fitz.Rect(110, 260, 500, 430)
    page.draw_rect(figure_rect, color=(0.1, 0.35, 0.55), fill=(0.78, 0.9, 0.86), width=2)
    page.draw_line((130, 400), (470, 290), color=(0.85, 0.2, 0.18), width=3)
    page.insert_text((112, 456), "Figure 1: Real PDF figure crop with visual content.", fontsize=10)
    page.insert_text((150, 520), "y = Wx + b (1)", fontsize=13)
    payload = document.tobytes()
    document.close()
    return payload


def _uncaptioned_image_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Uncaptioned Image Paper", fontsize=20)
    page.insert_textbox(
        fitz.Rect(72, 112, 540, 180),
        "This paragraph is real PDF body text. The image below is decorative and has no Figure caption.",
        fontsize=11,
    )
    page.insert_image(
        fitz.Rect(72, 220, 220, 340),
        stream=_sample_png_bytes(),
    )
    payload = document.tobytes()
    document.close()
    return payload


def _layout_provider_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Model Layout Paper", fontsize=20)
    page.insert_textbox(
        fitz.Rect(72, 112, 540, 170),
        "This paragraph is real paper text from the PDF. The model layout provider should only locate assets.",
        fontsize=11,
    )
    figure_rect = fitz.Rect(90, 210, 290, 370)
    page.draw_rect(figure_rect, color=(0.1, 0.35, 0.55), fill=(0.78, 0.9, 0.86), width=2)
    page.draw_line((105, 350), (275, 230), color=(0.85, 0.2, 0.18), width=3)
    page.insert_text((90, 386), "Figure 1: Figure located by the model layout provider.", fontsize=10)
    table_rect = fitz.Rect(320, 210, 520, 370)
    page.draw_rect(table_rect, color=(0.15, 0.15, 0.15), fill=(0.96, 0.96, 0.9), width=1)
    for x in (386, 452):
        page.draw_line((x, 210), (x, 370), color=(0.15, 0.15, 0.15), width=1)
    for y in (250, 290, 330):
        page.draw_line((320, y), (520, y), color=(0.15, 0.15, 0.15), width=1)
    page.insert_text((330, 235), "Method", fontsize=9)
    page.insert_text((395, 235), "Score", fontsize=9)
    page.insert_text((462, 235), "Delta", fontsize=9)
    page.insert_text((320, 386), "Table 1: Table located by the model layout provider.", fontsize=10)
    page.insert_text((150, 446), "y = Wx + b (1)", fontsize=13)
    payload = document.tobytes()
    document.close()
    return payload


def _model_equation_text_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Model Equation Paper", fontsize=20)
    page.insert_textbox(
        fitz.Rect(72, 118, 540, 160),
        "This paragraph is real paper text from the PDF before the equation.",
        fontsize=11,
    )
    page.insert_textbox(
        fitz.Rect(72, 180, 540, 222),
        "Given a data sample x0, the forward process gradually perturbs it with Gaussian noise under a variance schedule alpha_t:",
        fontsize=11,
    )
    payload = document.tobytes()
    document.close()
    return payload


def _noisy_visual_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Clean Body Paper", fontsize=20)
    page.insert_text((72, 112), "Abstract", fontsize=16)
    page.insert_textbox(
        fitz.Rect(72, 142, 540, 225),
        "Existing ap-\nproaches often encode text and reference images separately. This sentence should be readable.",
        fontsize=11,
    )
    figure_rect = fitz.Rect(96, 276, 516, 476)
    page.draw_rect(figure_rect, color=(0.1, 0.35, 0.55), fill=(0.78, 0.9, 0.86), width=2)
    page.insert_text((126, 330), "CLIP-T", fontsize=11)
    page.insert_text((126, 370), "Reference Image", fontsize=11)
    page.insert_text((360, 350), "Approaches", fontsize=11)
    page.insert_text((126, 488), "Method [1] 22.6 7.0 0.486 DreamO [2] 22.1 9.6 0.372", fontsize=9)
    page.insert_text((112, 512), "Figure 1:", fontsize=10)
    page.insert_text((112, 528), "A real multi-line figure caption from the paper.", fontsize=10)
    page.insert_text((306, 740), "1", fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def _multi_image_figure_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Multi Image Figure Paper", fontsize=20)
    page.insert_textbox(
        fitz.Rect(72, 112, 540, 170),
        "This paragraph is real paper text. The figure below is composed of several embedded image blocks.",
        fontsize=11,
    )
    image = _sample_png_bytes()
    for index, rect in enumerate(
        (
            fitz.Rect(96, 220, 196, 320),
            fitz.Rect(216, 220, 316, 320),
            fitz.Rect(96, 340, 196, 440),
            fitz.Rect(216, 340, 316, 440),
        )
    ):
        page.insert_image(rect, stream=image)
        page.insert_text((rect.x0, rect.y1 + 12), f"Panel {index + 1}", fontsize=8)
    page.insert_text((96, 480), "Figure 1: One multi-panel figure with a single caption.", fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def _two_column_image_figure_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Two Column Figure Paper", fontsize=20)
    page.insert_text((72, 112), "1 Introduction", fontsize=16)
    page.insert_textbox(
        fitz.Rect(72, 150, 285, 430),
        "Left column prose must stay readable in the article body. "
        "The compiler should not crop this paragraph into the visual asset. "
        "This sentence continues the real paper discussion.",
        fontsize=10,
    )
    image = _sample_png_bytes()
    for rect in (
        fitz.Rect(326, 230, 386, 290),
        fitz.Rect(408, 230, 468, 290),
        fitz.Rect(326, 318, 386, 378),
        fitz.Rect(408, 318, 468, 378),
    ):
        page.insert_image(rect, stream=image)
    page.insert_text((326, 214), "Panel prompt", fontsize=7)
    page.insert_text((326, 392), "Reference Image", fontsize=7)
    page.insert_text(
        (306, 424),
        "Figure 1: A multi-panel figure that lives in the right column.",
        fontsize=10,
    )
    payload = document.tobytes()
    document.close()
    return payload


def _sample_png_bytes() -> bytes:
    import fitz

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pixmap.clear_with(0x336699)
    return pixmap.tobytes("png")


def _sample_figure_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=240, height=140)
    page.draw_rect(fitz.Rect(16, 16, 224, 124), color=(0.1, 0.2, 0.5), fill=(0.82, 0.92, 0.86), width=2)
    page.draw_line((28, 112), (212, 34), color=(0.8, 0.1, 0.1), width=3)
    page.insert_text((28, 72), "Source asset", fontsize=14)
    payload = document.tobytes()
    document.close()
    return payload


def _sample_arxiv_source_tarball() -> bytes:
    files = {
        "00README.json": json.dumps(
            {
                "sources": [
                    {
                        "usage": "toplevel",
                        "filename": "main.tex",
                    }
                ],
                "spec_version": 1,
            }
        ),
        "main.tex": r"""
\documentclass{article}
\usepackage{graphicx}
\title{Source First Paper}
\begin{document}
\maketitle
\input{sections/body}
\end{document}
""",
        "sections/body.tex": r"""
\begin{abstract}
This abstract is from the TeX source package.
\end{abstract}

\section{Introduction from TeX source}
This paragraph is the real paper body from TeX source. It references Figure~\ref{fig:source} and Table~\ref{tab:source}.

\begin{figure}[t]
  \centering
  \includegraphics[width=\linewidth]{img/figure.pdf}
  \caption{A figure restored from the arXiv source asset.}
  \label{fig:source}
\end{figure}

\subsection{Formula}
The next display equation should be emitted as LaTeX text, not as a screenshot.
\begin{equation}
q(\mathbf{x}_t\mid\mathbf{x}_0) = \mathcal{N}(\mathbf{x}_t; \sqrt{\alpha_t}\mathbf{x}_0, (1-\alpha_t)\mathbf{I})
\end{equation}

\begin{table}[t]
\caption{A table restored from TeX source.}
\label{tab:source}
\begin{tabular}{lc}
\toprule
Method & Score \\
\midrule
Ours & 0.99 \\
\bottomrule
\end{tabular}
\end{table}
""",
        "img/figure.pdf": _sample_figure_pdf_bytes(),
    }
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return stream.getvalue()


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


class _FakeWorkerService:
    def enqueue_paper_visual_compile(self, *, paper_id, force=False, run_id=None):
        class Result:
            def to_dict(self):
                return {
                    "message_id": "1-0",
                    "task_id": "visual-task",
                    "task_type": "papers.visual_compile",
                    "queue_name": "news:queue:papers",
                    "status": "queued",
                    "paper_id": paper_id,
                    "force": force,
                    "run_id": run_id,
                }

        return Result()


class _FakeLayoutProvider:
    provider_name = "fake-model-layout-v1"

    def detect_regions(self, **_kwargs):
        return PaperLayoutDetection(
            regions=(
                PaperLayoutRegion(
                    kind="figure",
                    label="Figure 1",
                    caption="Figure 1: Figure located by the model layout provider.",
                    bbox=(90, 210, 290, 370),
                    confidence=0.98,
                ),
                PaperLayoutRegion(
                    kind="table",
                    label="Table 1",
                    caption="Table 1: Table located by the model layout provider.",
                    bbox=(320, 210, 520, 370),
                    confidence=0.97,
                ),
                PaperLayoutRegion(
                    kind="equation",
                    label=None,
                    caption=None,
                    bbox=(150, 430, 390, 460),
                    confidence=0.96,
                ),
            )
        )


class _CleanBodyLayoutProvider:
    provider_name = "clean-body-model-layout-v1"

    def detect_regions(self, **_kwargs):
        return PaperLayoutDetection(
            regions=(
                PaperLayoutRegion(
                    kind="figure",
                    label="Figure 1",
                    caption="Figure 1: A real multi-line figure caption from the paper.",
                    bbox=(96, 276, 516, 476),
                    confidence=0.99,
                ),
            )
        )


class _ModelEquationTextLayoutProvider:
    provider_name = "model-equation-text-layout-v1"

    def detect_regions(self, **_kwargs):
        return PaperLayoutDetection(
            regions=(
                PaperLayoutRegion(
                    kind="equation",
                    label="Equation 1",
                    caption=None,
                    bbox=(72, 180, 540, 222),
                    confidence=0.99,
                    metadata={
                        "equationText": r"q(x_t \mid x_0)=\mathcal{N}(x_t;\sqrt{\alpha_t}x_0,(1-\alpha_t)I)",
                    },
                ),
            )
        )
