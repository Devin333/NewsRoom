import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { mapReplayBundle } from "@/features/studio/artifacts/lib/artifact-adapter"
import { LineageViewer } from "@/features/studio/artifacts/components/lineage-viewer"
import { ReplayBundleViewer } from "@/features/studio/artifacts/components/replay-bundle-viewer"

describe("ReplayBundleViewer", () => {
  it("shows replay readiness and integrity", () => {
    const replay = mapReplayBundle({
      run_id: "run-1",
      manifest: { run_id: "run-1" },
      event_count: 1,
      events: [{ event_type: "workflow_started" }],
      artifact_count: 1,
      artifacts: [{ artifact_key: "manifest", relative_path: "manifest.json", content_type: "application/json" }],
      step_result_count: 1,
      step_results: { collect: { status: "succeeded" } },
      integrity: { valid: true }
    })

    render(<ReplayBundleViewer replay={replay} />)

    expect(screen.getByText("可复盘")).toBeInTheDocument()
    expect(screen.getByText("valid")).toBeInTheDocument()
  })

  it("shows events_error and not-ready state", () => {
    const replay = mapReplayBundle({
      run_id: "run-1",
      manifest: { run_id: "run-1" },
      event_count: 0,
      events: [],
      artifact_count: 1,
      artifacts: [{ artifact_key: "manifest", relative_path: "manifest.json", content_type: "application/json" }],
      step_result_count: 0,
      step_results: {},
      integrity: { valid: false },
      events_error: "events artifact not found"
    })

    render(<ReplayBundleViewer replay={replay} />)

    expect(screen.getByText("需要检查")).toBeInTheDocument()
    expect(screen.getByText("events artifact not found")).toBeInTheDocument()
  })

  it("shows empty lineage state", () => {
    render(<LineageViewer lineage={[]} />)

    expect(screen.getByText("No lineage")).toBeInTheDocument()
  })
})
