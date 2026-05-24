"use client"

import { TaskDetailPage } from "@/components/papers/tasks/task-detail-page"
import type { Paper, PaperTask } from "@/lib/papers/types"
import { useUiStore } from "@/stores/ui-store"

export function TaskDetailPageClient({ task, papers }: { task: PaperTask; papers: Paper[] }) {
  const locale = useUiStore((state) => state.locale)

  return <TaskDetailPage task={task} locale={locale} papers={papers} />
}
