"use client"

import { ArtifactViewer } from "@/features/studio/runs/components/artifact-viewer"
import { ErrorTracePanel } from "@/features/studio/runs/components/error-trace-panel"
import { MemoryHitList } from "@/features/studio/runs/components/memory-hit-list"
import { RunLogList } from "@/features/studio/runs/components/run-log-list"
import { RunQualityPanel } from "@/features/studio/runs/components/run-quality-panel"
import { ToolCallList } from "@/features/studio/runs/components/tool-call-list"
import { useRunInspectorStore, type InspectorTab } from "@/stores/run-inspector-store"
import type { AgentRunDetail } from "@/types/agent"

const tabs: Array<{ id: InspectorTab; label: string }> = [
  { id: "logs", label: "日志" },
  { id: "tools", label: "工具调用" },
  { id: "memory", label: "记忆命中" },
  { id: "artifacts", label: "产物" },
  { id: "quality", label: "质量" },
  { id: "errors", label: "错误" }
]

export function RunInspectorTabs({ detail }: { detail: AgentRunDetail }) {
  const activeTab = useRunInspectorStore((state) => state.activeTab)
  const setActiveTab = useRunInspectorStore((state) => state.setActiveTab)

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
      <div className="max-h-[720px] overflow-auto p-4">
        {activeTab === "logs" ? <RunLogList logs={detail.logs} /> : null}
        {activeTab === "tools" ? <ToolCallList calls={detail.toolCalls} /> : null}
        {activeTab === "memory" ? <MemoryHitList hits={detail.memoryHits} /> : null}
        {activeTab === "artifacts" ? <ArtifactViewer artifacts={detail.artifacts} /> : null}
        {activeTab === "quality" ? <RunQualityPanel quality={detail.quality} /> : null}
        {activeTab === "errors" ? <ErrorTracePanel errors={detail.errors} /> : null}
      </div>
    </section>
  )
}
