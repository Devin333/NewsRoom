import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { methodName, taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, MethodRef, TaskRef } from "@/lib/papers/types"

export function PaperTags({
  tasks,
  methods,
  tags,
  locale
}: {
  tasks: TaskRef[]
  methods: MethodRef[]
  tags: string[]
  locale: Locale
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {tasks.slice(0, 2).map((task) => (
        <Link key={task.id} href={papersRoutes.taskDetail(task.slug)}>
          <Badge variant="accent" className="rounded-full border-emerald-300 bg-emerald-50 font-mono text-[0.68rem] text-emerald-700">{taskName(task, locale)}</Badge>
        </Link>
      ))}
      {methods.slice(0, 2).map((method) => (
        <Link key={method.id} href={papersRoutes.methodDetail(method.slug)}>
          <Badge variant="success" className="rounded-full border-blue-300 bg-blue-50 font-mono text-[0.68rem] text-blue-700">{methodName(method, locale)}</Badge>
        </Link>
      ))}
      {tags.slice(0, 2).map((tag) => (
        <Badge key={tag} variant="muted" className="rounded-full font-mono text-[0.68rem]">
          {tag}
        </Badge>
      ))}
    </div>
  )
}
