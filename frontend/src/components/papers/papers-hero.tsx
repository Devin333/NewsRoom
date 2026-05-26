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
    const [firstWord, ...rest] = title.split(" ")
    return (
      <section className="grid gap-8 py-12 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-end">
        <div>
          {eyebrow ? (
            <p className="mb-5 text-xs font-medium uppercase tracking-[0.18em] text-[#334155]/55">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="max-w-5xl break-keep text-5xl font-black leading-none tracking-normal text-[#334155] sm:text-6xl lg:text-7xl dark:text-foreground">
            {firstWord}{" "}
            <span className="bg-gradient-to-r from-emerald-600 via-teal-600 to-blue-600 bg-clip-text text-transparent">
              {rest.join(" ")}
            </span>
          </h1>
          <p className="mt-6 max-w-3xl text-base leading-7 text-[#334155]/70 dark:text-muted-foreground">{subtitle}</p>
        </div>
        <div className="w-full max-w-[18rem] space-y-3 justify-self-start sm:justify-self-end">
          <div className="rounded-3xl border border-[#dbe3dc] bg-white/85 p-4 shadow-[0_24px_60px_rgba(15,23,42,0.10)] dark:border-border dark:bg-card">
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
