"use client"

import { TasksPage } from "@/components/papers/tasks/tasks-page"
import { useUiStore } from "@/stores/ui-store"

export default function PapersTasksPageRoute() {
  const locale = useUiStore((state) => state.locale)

  return <TasksPage locale={locale} />
}
