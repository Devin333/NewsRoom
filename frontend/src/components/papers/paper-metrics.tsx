import type { ReactNode } from "react"
import { ArrowUpRight, Github, Quote, Star } from "lucide-react"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatCompactNumber } from "@/lib/papers/format"
import type { Locale, Paper } from "@/lib/papers/types"

export function PaperMetrics({ paper, locale }: { paper: Paper; locale: Locale }) {
  return (
    <div className="grid gap-3">
      <Metric icon={<Github className="size-4" />} value={formatCompactNumber(paper.githubStars)} label={t(papersCopy.githubStars, locale)} />
      <Metric icon={<ArrowUpRight className="size-4" />} value={paper.starsPerHour?.toFixed(1) ?? "0.0"} label={t(papersCopy.starsPerHour, locale)} tone="green" />
      <Metric icon={<Quote className="size-4" />} value={formatCompactNumber(paper.citationCount)} label={t(papersCopy.citations, locale)} />
    </div>
  )
}

function Metric({
  icon,
  value,
  label,
  tone = "neutral"
}: {
  icon: ReactNode
  value: string
  label: string
  tone?: "neutral" | "green"
}) {
  return (
    <div className="flex items-center gap-2.5 text-left">
      <span className={tone === "green" ? "text-emerald-600" : "text-slate-500 dark:text-muted-foreground"}>{icon}</span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 font-mono text-base font-black leading-5 text-[#111827] dark:text-foreground">
          {value}
          {label.includes("GitHub") ? <Star className="size-3 text-amber-500" /> : null}
        </span>
        <span className="block truncate text-[0.68rem] font-medium leading-4 text-slate-500 dark:text-muted-foreground">
          {label}
        </span>
      </span>
    </div>
  )
}
