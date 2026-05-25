import { notFound } from "next/navigation"
import { TaskDetailPageClient } from "@/app/papers/tasks/[slug]/task-detail-page-client"
import { getTaskBySlug, paperTasks } from "@/lib/papers/catalog"
import { getPublishedPapers, loadApiPaperTasks } from "@/lib/papers/real-data"

export function generateStaticParams() {
  return paperTasks.map((task) => ({ slug: task.slug }))
}

export default async function PapersTaskDetailPageRoute({ params }: { params: { slug: string } }) {
  const apiTasks = await loadApiPaperTasks()
  const task = apiTasks.find((item) => item.slug === params.slug) ?? getTaskBySlug(params.slug)

  if (!task) {
    notFound()
  }

  return (
    <TaskDetailPageClient
      task={task}
      papers={await getPublishedPapers()}
      fallbackNotice={apiTasks.length ? null : "Paper task API is unavailable; showing local catalog fallback."}
    />
  )
}
