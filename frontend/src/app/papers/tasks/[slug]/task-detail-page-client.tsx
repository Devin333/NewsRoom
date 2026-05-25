"use client"

import { TaskDetailPage } from "@/components/papers/tasks/task-detail-page"
import type { Paper, PaperTask } from "@/lib/papers/types"
import { useUiStore } from "@/stores/ui-store"

export function TaskDetailPageClient({
  task,
  papers,
  fallbackNotice
}: {
  task: PaperTask
  papers: Paper[]
  fallbackNotice?: string | null
}) {
  const locale = useUiStore((state) => state.locale)

  return <TaskDetailPage task={task} locale={locale} papers={papers} fallbackNotice={fallbackNotice} />
}
