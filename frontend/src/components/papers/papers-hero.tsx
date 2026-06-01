import type { ReactNode } from "react"
import { SummaryCard } from "@/components/papers/summary-card"
import { cn } from "@/lib/utils"

export function PapersHero({
  eyebrow,
  title,
  subtitle,
  stats,
  aside,
  variant = "default"
}: {
  eyebrow?: string
  title: string
  subtitle: string
  stats: Array<{ label: string; value: string | number }>
  aside?: ReactNode
  variant?: "default" | "editorial"
}) {
  if (variant === "editorial") {
    return (
      <section className="grid gap-5 py-5 lg:grid-cols-[minmax(0,1fr)_21rem] lg:items-end">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/55">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="max-w-3xl break-keep text-3xl font-semibold leading-tight tracking-normal text-[#1f2933] sm:text-4xl dark:text-foreground">
            {title}
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-[#334155]/68 dark:text-muted-foreground">
            {subtitle}
          </p>
        </div>
        <div className="w-full max-w-[21rem] space-y-2.5 justify-self-start lg:justify-self-end">
          <div className="rounded-xl border border-[#dfe5df] bg-white/80 p-2.5 shadow-sm dark:border-border dark:bg-card">
            <div className="grid grid-cols-3 gap-2">
              {stats.map((stat) => (
                <SummaryCard key={stat.label} label={stat.label} value={stat.value} compact />
              ))}
            </div>
          </div>
          {aside ? <div className="w-full">{aside}</div> : null}
        </div>
      </section>
    )
  }

  return (
    <section className={cn("rounded-md border border-border bg-card p-5")}>
      {eyebrow ? <p className="text-sm font-semibold uppercase text-primary">{eyebrow}</p> : null}
      <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">{title}</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">{subtitle}</p>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        {stats.map((stat) => (
          <SummaryCard key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </div>
    </section>
  )
}
