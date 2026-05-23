"use client"

import { Badge } from "@/components/common/badge"
import { formatRunStatus, statusTone } from "@/features/studio/runs/lib/run-format"
import { useRunInspectorStore } from "@/stores/run-inspector-store"
import type { AgentStep } from "@/types/agent"

export function StepTimeline({ steps }: { steps: AgentStep[] }) {
  const selectedStepId = useRunInspectorStore((state) => state.selectedStepId)
  const selectStep = useRunInspectorStore((state) => state.selectStep)
  const setActiveTab = useRunInspectorStore((state) => state.setActiveTab)

  return (
    <ol className="space-y-2">
      {steps.map((step) => (
        <li key={step.id}>
          <button
            type="button"
            className={`w-full rounded-md border p-3 text-left transition-colors ${
              selectedStepId === step.id ? "border-primary bg-primary/10" : "border-border bg-card hover:bg-secondary"
            }`}
            onClick={() => {
              selectStep(step.nodeId, step.id)
              if (step.status === "failed") setActiveTab("errors")
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-medium text-foreground">{step.label}</span>
              <Badge tone={statusTone(step.status)}>{formatRunStatus(step.status)}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{step.type}</p>
          </button>
        </li>
      ))}
    </ol>
  )
}
