import type { Artifact } from "@/types/artifact"

export const studioArtifactFixtures: Artifact[] = [
  {
    id: "artifact-manifest",
    runId: "run-daily-20260522-0800",
    stepId: "step-collect",
    artifactType: "json",
    filename: "manifest.json",
    sizeBytes: 2048,
    createdAt: "2026-05-22T08:54:00.000Z",
    preview: JSON.stringify({ replay_sections: ["manifest", "events", "step_results"] }, null, 2)
  },
  {
    id: "artifact-events",
    runId: "run-daily-20260522-0800",
    stepId: "step-quality",
    artifactType: "log",
    filename: "events.jsonl",
    sizeBytes: 8192,
    createdAt: "2026-05-22T08:54:30.000Z",
    preview: '{"event_type":"quality_gate_failed","step_id":"step-quality"}'
  },
  {
    id: "artifact-step-results",
    runId: "run-daily-20260522-0800",
    stepId: "step-quality",
    artifactType: "json",
    filename: "step_results.json",
    sizeBytes: 4096,
    createdAt: "2026-05-22T08:55:00.000Z",
    preview: JSON.stringify({ step_results: [{ step_id: "step-quality", status: "failed" }] }, null, 2)
  }
]

export const studioReplayBundleFixture = {
  runId: "run-daily-20260522-0800",
  sections: ["manifest", "events", "step_results"],
  manifest: { run_id: "run-daily-20260522-0800", status: "failed" },
  events: [{ event_type: "quality_gate_failed", step_id: "step-quality" }],
  step_results: [{ step_id: "step-quality", status: "failed" }]
} as const
