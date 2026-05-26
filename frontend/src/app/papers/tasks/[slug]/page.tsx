import { notFound } from "next/navigation"
import { TaskDetailPageClient } from "@/app/papers/tasks/[slug]/task-detail-page-client"
import { getTaskBySlug, paperTasks } from "@/lib/papers/catalog"
import { getPaperTasksResult, getPublishedPapers } from "@/lib/papers/real-data"

export function generateStaticParams() {
  return paperTasks.map((task) => ({ slug: task.slug }))
}

export default async function PapersTaskDetailPageRoute({ params }: { params: { slug: string } }) {
  const result = await getPaperTasksResult()
  const task = result.items.find((item) => item.slug === params.slug) ?? getTaskBySlug(params.slug)

  if (!task) {
    notFound()
  }

  return (
    <TaskDetailPageClient
      task={task}
      papers={await getPublishedPapers()}
      fallbackNotice={result.source === "backend" ? null : result.notices[0] ?? null}
    />
  )
}
