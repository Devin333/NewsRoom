import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ARTIFACT_PREVIEW_LIMIT_BYTES, mapArtifact } from "@/features/studio/artifacts/lib/artifact-adapter"
import { ArtifactPreview } from "@/features/studio/artifacts/components/artifact-preview"

describe("ArtifactPreview", () => {
  it("renders pretty JSON", () => {
    const artifact = mapArtifact(
      {
        artifact_key: "manifest",
        relative_path: "manifest.json",
        content_type: "application/json",
        content: { status: "succeeded" }
      },
      "run-1"
    )

    render(<ArtifactPreview artifact={artifact} />)

    expect(screen.getByText(/"status": "succeeded"/)).toBeInTheDocument()
  })

  it("renders markdown preview", () => {
    const artifact = mapArtifact(
      {
        artifact_key: "report_markdown",
        relative_path: "report.md",
        content_type: "text/markdown",
        content: "# Report\n\nBody"
      },
      "run-1"
    )

    render(<ArtifactPreview artifact={artifact} />)

    expect(screen.getByRole("heading", { name: "Report" })).toBeInTheDocument()
  })

  it("escapes HTML instead of executing or injecting it", () => {
    const artifact = mapArtifact(
      {
        artifact_key: "html",
        relative_path: "report.html",
        content_type: "text/html",
        content: "<script>window.bad = true</script><h1>Unsafe</h1>"
      },
      "run-1"
    )

    const { container } = render(<ArtifactPreview artifact={artifact} />)

    expect(screen.getByText(/<script>window.bad = true<\/script>/)).toBeInTheDocument()
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("h1")).toBeNull()
  })

  it("shows binary metadata only", () => {
    const artifact = mapArtifact(
      {
        artifact_key: "dataset",
        relative_path: "dataset.parquet",
        content_type: "application/octet-stream",
        size_bytes: 2048
      },
      "run-1"
    )

    render(<ArtifactPreview artifact={artifact} />)

    expect(screen.getByText("二进制产物不渲染正文")).toBeInTheDocument()
    expect(screen.getByText("2.0 KB")).toBeInTheDocument()
  })

  it("shows a truncation notice for large text", () => {
    const artifact = mapArtifact(
      {
        artifact_key: "large_log",
        relative_path: "large.log",
        content_type: "text/plain",
        size_bytes: ARTIFACT_PREVIEW_LIMIT_BYTES + 1,
        content: "x".repeat(ARTIFACT_PREVIEW_LIMIT_BYTES + 1)
      },
      "run-1"
    )

    render(<ArtifactPreview artifact={artifact} />)

    expect(screen.getByText("内容超过 100KB，已截断预览。")).toBeInTheDocument()
  })
})
