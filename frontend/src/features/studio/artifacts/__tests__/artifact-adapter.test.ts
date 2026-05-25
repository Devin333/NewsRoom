import { describe, expect, it } from "vitest"
import {
  ARTIFACT_PREVIEW_LIMIT_BYTES,
  buildPreview,
  mapArtifact,
  mapLineage,
  mapReplayBundle,
  previewKindFor
} from "@/features/studio/artifacts/lib/artifact-adapter"

describe("artifact adapter", () => {
  it("maps replay response into a replay bundle view model", () => {
    const bundle = mapReplayBundle({
      run_id: "run-1",
      manifest_path: ".newsroom/runs/run-1/manifest.json",
      manifest: { run_id: "run-1" },
      event_count: 1,
      events: [{ event_type: "workflow_started" }],
      artifact_count: 1,
      artifacts: [
        {
          artifact_key: "report_json",
          relative_path: "report.json",
          content_type: "application/json",
          size_bytes: 24,
          content: { title: "Report" }
        }
      ],
      step_result_count: 1,
      step_results: { report: { status: "succeeded" } },
      integrity: { valid: true }
    })

    expect(bundle.ready).toBe(true)
    expect(bundle.artifacts[0].previewKind).toBe("json")
    expect(bundle.artifacts[0].previewText).toContain('"title": "Report"')
    expect(bundle.stepResultCount).toBe(1)
  })

  it("maps lineage refs into upstream list rows", () => {
    const lineage = mapLineage(
      {
        run_id: "run-1",
        lineage_refs: [
          {
            lineage_id: "lin-1",
            run_id: "run-1",
            source_type: "source_item",
            source_id: "raw-1",
            target_type: "evidence",
            target_id: "ev-1",
            relation_type: "source_to_evidence"
          }
        ]
      },
      "upstream"
    )

    expect(lineage).toEqual([
      expect.objectContaining({
        direction: "upstream",
        sourceType: "source_item",
        targetId: "ev-1"
      })
    ])
  })

  it("detects preview kind from content type and extension", () => {
    expect(previewKindFor("application/json", "manifest.json")).toBe("json")
    expect(previewKindFor("text/markdown", "report.md")).toBe("markdown")
    expect(previewKindFor("text/html", "report.html")).toBe("html")
    expect(previewKindFor("application/octet-stream", "dataset.parquet")).toBe("binary")
  })

  it("guards large text previews", () => {
    const preview = buildPreview("x".repeat(ARTIFACT_PREVIEW_LIMIT_BYTES + 10), "text")

    expect(preview.truncated).toBe(true)
    expect(preview.notice).toContain("100KB")
  })

  it("marks redacted artifact content", () => {
    const artifact = mapArtifact(
      {
        artifact_key: "secret",
        relative_path: "secret.json",
        content_type: "application/json",
        content: { api_key: "[redacted]" }
      },
      "run-1"
    )

    expect(artifact.redacted).toBe(true)
  })
})
