import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { papersCopy, t } from "@/lib/papers/copy"
import { methodName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, PaperMethod } from "@/lib/papers/types"

export function MethodCard({ method, locale }: { method: PaperMethod; locale: Locale }) {
  return (
    <Link
      href={papersRoutes.methodDetail(method.slug)}
      className="group rounded-md border border-border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-secondary/30"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{methodName(method, locale)}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {method.paperCount} {t(papersCopy.papers, locale)} · {method.taskCount} {t(papersCopy.tasks, locale)} · {method.area}
          </p>
        </div>
        <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Badge variant="accent">{method.paperCount} {t(papersCopy.papers, locale)}</Badge>
        <Badge variant="success">{method.taskCount} {t(papersCopy.tasks, locale)}</Badge>
        <Badge variant="muted">{method.area}</Badge>
      </div>
    </Link>
  )
}
