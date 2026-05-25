"use client"

import { useEffect, useMemo } from "react"
import { Badge } from "@/components/common/badge"
import { ErrorState } from "@/components/common/error-state"
import { EmptyState } from "@/components/common/empty-state"
import { PageHeader } from "@/components/layout/page-header"
import { RunDetailHeader } from "@/features/studio/runs/components/run-detail-header"
import { RunDetailInspector } from "@/features/studio/runs/components/run-detail-inspector"
import { StepDetailPanel } from "@/features/studio/runs/components/step-detail-panel"
import { StepTimeline } from "@/features/studio/runs/components/step-timeline"
import { WorkflowDag } from "@/features/studio/runs/components/workflow-dag"
import { useRunDetail } from "@/features/studio/runs/hooks/use-run-detail"
import { useRunInspectorStore } from "@/stores/run-inspector-store"
import type { StudioRunDetail } from "@/types/agent"

export function RunCenterDetailPage({ runId, detail }: { runId: string; detail?: StudioRunDetail }) {
  const { data, isError, error } = useRunDetail(runId, detail)
  const selectedStepId = useRunInspectorStore((state) => state.selectedStepId)
  const selectStep = useRunInspectorStore((state) => state.selectStep)

  const defaultStep = useMemo(() => {
    if (!data?.steps.length) return undefined
    return data.steps.find((step) => step.status === "failed" || step.status === "blocked") ?? data.steps.find((step) => step.status === "running") ?? data.steps[0]
  }, [data])

  useEffect(() => {
    if (defaultStep && (!selectedStepId || !data?.steps.some((step) => step.id === selectedStepId))) {
      selectStep(defaultStep.nodeId, defaultStep.id)
    }
  }, [data?.steps, defaultStep, selectStep, selectedStepId])

  if (isError || !data) {
    return <ErrorState message={error instanceof Error ? error.message : "Run detail failed to load."} />
  }

  const selectedStep = data.steps.find((step) => step.id === selectedStepId) ?? defaultStep

  return (
    <main className="space-y-6">
      <PageHeader
        eyebrow="Studio Run"
        title="Run Observability"
        description="Inspect steps, events, diagnostics, health, artifacts, errors, and runtime operations for this workflow run."
      />
      <RunDetailHeader run={data.run} />

      {data.notices.length ? (
        <div className="flex flex-wrap gap-2">
          {data.notices.map((notice) => (
            <Badge key={notice} tone={data.dataState === "ready" ? "success" : "warning"}>{notice}</Badge>
          ))}
        </div>
      ) : null}

      {data.run.artifactDir || data.run.manifestPath || data.run.reportId ? (
        <section className="grid gap-3 rounded-lg border border-border bg-card p-4 text-sm md:grid-cols-3">
          <Meta label="Report" value={data.run.reportId} />
          <Meta label="Artifact directory" value={data.run.artifactDir} />
          <Meta label="Manifest" value={data.run.manifestPath} />
        </section>
      ) : null}

      {!data.steps.length ? (
        <EmptyState title="No steps" description="This run does not include step records." />
      ) : (
        <section className="grid gap-6 2xl:grid-cols-[minmax(300px,0.9fr)_minmax(360px,1fr)_minmax(420px,1.1fr)]">
          <div className="hidden 2xl:block">
            <WorkflowDag nodes={data.dag.nodes} edges={data.dag.edges} />
          </div>
          <div className="2xl:hidden">
            <StepTimeline steps={data.steps} />
          </div>
          <StepDetailPanel step={selectedStep} />
          <RunDetailInspector detail={data} selectedStep={selectedStep} />
        </section>
      )}
    </main>
  )
}

function Meta({ label, value }: { label: string; value?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-mono text-xs text-foreground">{value ?? "None"}</p>
    </div>
  )
}
