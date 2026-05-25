"use client"

import { useState } from "react"
import Link from "next/link"
import { ArrowLeft, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StudioFallbackNotice } from "@/features/studio/shared/components/studio-fallback-notice"
import { StudioPageHeader, StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import { BoardCardGrid } from "@/features/studio/boards/components/board-card-grid"
import { BoardOutputPanel } from "@/features/studio/boards/components/board-output-panel"
import { CrossBoardInsightPanel } from "@/features/studio/boards/components/cross-board-insight-panel"
import { useBoardList } from "@/features/studio/boards/hooks/use-board-list"
import { useBoardOutput } from "@/features/studio/boards/hooks/use-board-output"
import type {
  StudioBoardDetailViewModel,
  StudioBoardListViewModel
} from "@/types/board"

export function BoardCenterPage({ initialData }: { initialData: StudioBoardListViewModel }) {
  const { data } = useBoardList(initialData)

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Business"
        title="Board Center"
        description="Business board objects for AI News, Project Radar, Paper Radar, Community Pulse, and Cross Board."
      />
      <NoticeList notices={data.notices} />
      <BoardCardGrid summaries={data.summaries} definitions={data.definitions} />
    </main>
  )
}

export function BoardDetailPage({ detail }: { detail: StudioBoardDetailViewModel }) {
  const { data: output, isLoading, buildOutput } = useBoardOutput(detail.summary.boardType, detail.output)
  const [itemsJson, setItemsJson] = useState(detail.sampleItemsJson)
  const [topic, setTopic] = useState("Agent Memory")
  const [formError, setFormError] = useState<string | undefined>()

  async function handleBuildOutput() {
    setFormError(undefined)
    let parsed: unknown
    try {
      parsed = JSON.parse(itemsJson)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Invalid JSON")
      return
    }

    if (!Array.isArray(parsed) || !parsed.every(isRecord)) {
      setFormError("Sample items must be a JSON array of objects.")
      return
    }

    await buildOutput({ items: parsed, topic: topic.trim() || undefined })
  }

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Board Center"
        title={detail.summary.title}
        description={detail.definition.description}
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/studio/boards">
              <ArrowLeft className="size-4" />
              Boards
            </Link>
          </Button>
        }
      />

      <NoticeList notices={[...detail.notices, ...detail.summary.notices, ...output.notices]} />

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <StudioPanel
          title="Board definition"
          description={detail.summary.boardType}
          actions={<Badge variant={detail.summary.status === "ready" ? "success" : "warning"}>{detail.summary.status}</Badge>}
        >
          <div className="grid gap-4 text-sm md:grid-cols-2">
            <DefinitionLine label="Input object" value={detail.definition.inputObject} />
            <DefinitionLine label="Output object" value={detail.definition.outputObject} />
            <DefinitionLine label="Signal types" value={detail.definition.signalTypes.join(", ")} />
            <DefinitionLine label="Visible sections" value={detail.definition.visibleSections.join(", ")} />
          </div>
        </StudioPanel>

        <Card>
          <CardHeader className="flex-row items-center gap-3">
            <div>
              <CardTitle>Build output</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">Generate a sample board response</p>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <label className="block text-sm font-medium text-foreground" htmlFor="board-topic">
              Topic
            </label>
            <input
              id="board-topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <label className="block text-sm font-medium text-foreground" htmlFor="board-sample-items">
              Sample items JSON
            </label>
            <textarea
              id="board-sample-items"
              value={itemsJson}
              onChange={(event) => setItemsJson(event.target.value)}
              className="min-h-[220px] w-full resize-y rounded-md border border-input bg-card px-3 py-2 font-mono text-xs text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            {formError ? (
              <p role="alert" className="text-sm text-danger">
                {formError}
              </p>
            ) : null}
            <Button onClick={handleBuildOutput} disabled={isLoading}>
              <Play className="size-4" />
              {isLoading ? "Building" : "Build output"}
            </Button>
          </CardContent>
        </Card>
      </section>

      {output.crossBoard ? <CrossBoardInsightPanel crossBoard={output.crossBoard} /> : null}
      <BoardOutputPanel output={output} />
    </main>
  )
}

function NoticeList({ notices }: { notices: string[] }) {
  const unique = [...new Set(notices.filter(Boolean))]
  if (!unique.length) return null
  return (
    <div className="space-y-3">
      {unique.map((notice) => (
        <StudioFallbackNotice key={notice} title="Board data notice" message={notice} />
      ))}
    </div>
  )
}

function DefinitionLine({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-foreground">{value}</p>
    </div>
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}
