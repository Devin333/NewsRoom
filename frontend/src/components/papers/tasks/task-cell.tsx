import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { papersCopy, t } from "@/lib/papers/copy"
import { taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, PaperTask } from "@/lib/papers/types"

export function TaskCell({ task, locale }: { task: PaperTask; locale: Locale }) {
  return (
    <Link
      href={papersRoutes.taskDetail(task.slug)}
      className="group rounded-md border border-border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-secondary/30"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{taskName(task, locale)}</h3>
          <p className="mt-2 text-xs text-muted-foreground">{task.paperCount} {t(papersCopy.papers, locale)}</p>
        </div>
        <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
      {task.trendSignal ? (
        <Badge variant="success" className="mt-4">
          {task.trendSignal}
        </Badge>
      ) : null}
    </Link>
  )
}
