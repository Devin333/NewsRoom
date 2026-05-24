import { notFound } from "next/navigation"
import { TaskDetailPageClient } from "@/app/papers/tasks/[slug]/task-detail-page-client"
import { getTaskBySlug, paperTasks } from "@/lib/papers/catalog"
import { getPublishedPapers } from "@/lib/papers/real-data"

export function generateStaticParams() {
  return paperTasks.map((task) => ({ slug: task.slug }))
}

export default async function PapersTaskDetailPageRoute({ params }: { params: { slug: string } }) {
  const task = getTaskBySlug(params.slug)

  if (!task) {
    notFound()
  }

  return <TaskDetailPageClient task={task} papers={await getPublishedPapers()} />
}
