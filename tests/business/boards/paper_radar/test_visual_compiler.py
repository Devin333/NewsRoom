import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from business.boards.paper_radar.visual_compiler import PaperAssetGate, PaperVisualCompilerRepository, PyMuPDFPaperCompiler
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

    visual_assets = [asset for asset in draft.manifest.assets if asset.kind in {"figure", "table", "equation"}]
    assert gate_report["passed"] is True
    assert visual_assets == []
    assert any(item["code"] == "uncaptioned_image_skipped" for item in draft.compile_info.diagnostics)


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


def _sample_png_bytes() -> bytes:
    import fitz

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pixmap.clear_with(0x336699)
    return pixmap.tobytes("png")


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
