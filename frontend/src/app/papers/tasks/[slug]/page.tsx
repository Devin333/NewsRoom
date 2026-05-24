import { notFound } from "next/navigation"
import { TaskDetailPageClient } from "@/app/papers/tasks/[slug]/task-detail-page-client"
import { getTaskBySlug, paperTasks } from "@/lib/papers/mock-data"
import { getPublishedPapers } from "@/lib/papers/real-data"

export function generateStaticParams() {
  return paperTasks.map((task) => ({ slug: task.slug }))
}

export default function PapersTaskDetailPageRoute({ params }: { params: { slug: string } }) {
  const task = getTaskBySlug(params.slug)

  if (!task) {
    notFound()
  }

  return <TaskDetailPageClient task={task} papers={getPublishedPapers()} />
}
