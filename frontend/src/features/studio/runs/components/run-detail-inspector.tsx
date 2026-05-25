"use client"

import { useState } from "react"
import { ArtifactViewer } from "@/features/studio/runs/components/artifact-viewer"
import { ErrorTracePanel } from "@/features/studio/runs/components/error-trace-panel"
import { JsonPreview } from "@/features/studio/runs/components/json-preview"
import { RunEventStream } from "@/features/studio/runs/components/run-event-stream"
import { RunOperationPanel } from "@/features/studio/runs/components/run-operation-panel"
import { RunQualityPanel } from "@/features/studio/runs/components/run-quality-panel"
import { ToolCallList } from "@/features/studio/runs/components/tool-call-list"
import type { AgentStep, StudioRunDetail } from "@/types/agent"

type RunCenterTab = "events" | "artifacts" | "quality" | "errors" | "diagnostics" | "health" | "operations" | "tools"

const tabs: Array<{ id: RunCenterTab; label: string }> = [
  { id: "events", label: "Events" },
  { id: "artifacts", label: "Artifacts" },
  { id: "quality", label: "Quality" },
  { id: "errors", label: "Errors" },
  { id: "diagnostics", label: "Diagnostics" },
  { id: "health", label: "Health" },
  { id: "operations", label: "Operations" },
  { id: "tools", label: "Tools" }
]

export function RunDetailInspector({ detail, selectedStep }: { detail: StudioRunDetail; selectedStep?: AgentStep }) {
  const [activeTab, setActiveTab] = useState<RunCenterTab>(() => {
    if (detail.dataState === "fallback") return "events"
    if (detail.run.status === "blocked" || detail.run.status === "waiting_for_human") return "operations"
    if (detail.errors.length) return "errors"
    return "events"
  })

  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex gap-1 overflow-x-auto border-b border-border p-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`h-8 shrink-0 rounded-md px-3 text-sm transition-colors ${
              activeTab === tab.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
            }`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="max-h-[760px] overflow-auto p-4">
        {activeTab === "events" ? <RunEventStream events={detail.events} /> : null}
        {activeTab === "artifacts" ? <ArtifactViewer artifacts={detail.artifacts} /> : null}
        {activeTab === "quality" ? <RunQualityPanel quality={detail.quality} /> : null}
        {activeTab === "errors" ? <ErrorTracePanel errors={detail.errors} /> : null}
        {activeTab === "diagnostics" ? <JsonPreview label="Diagnostics" value={detail.diagnostics} defaultOpen /> : null}
        {activeTab === "health" ? <JsonPreview label="Health" value={detail.health} defaultOpen /> : null}
        {activeTab === "operations" ? <RunOperationPanel detail={detail} selectedStep={selectedStep} /> : null}
        {activeTab === "tools" ? <ToolCallList calls={detail.toolCalls} /> : null}
      </div>
    </section>
  )
}
