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
    const [leadingTitle, accentTitle] = splitEditorialTitle(title)
    return (
      <section className="grid gap-6 pt-5 pb-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start xl:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="mb-5 text-xs font-medium uppercase tracking-[0.18em] text-[#334155]/55">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="max-w-4xl break-keep text-4xl font-black leading-[0.96] tracking-normal text-[#334155] sm:text-5xl lg:text-6xl dark:text-foreground">
            {accentTitle ? (
              <>
                {leadingTitle}{" "}
                <span className="bg-gradient-to-r from-emerald-600 via-teal-600 to-blue-600 bg-clip-text text-transparent">
                  {accentTitle}
                </span>
              </>
            ) : (
              leadingTitle
            )}
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-[#334155]/70 dark:text-muted-foreground sm:text-[0.95rem]">
            {subtitle}
          </p>
        </div>
        <div className="w-full max-w-[21rem] space-y-2.5 justify-self-start sm:justify-self-end">
          <div className="rounded-2xl border border-[#dbe3dc] bg-white/85 p-3.5 shadow-[0_18px_42px_rgba(15,23,42,0.08)] dark:border-border dark:bg-card">
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

function splitEditorialTitle(title: string): [string, string | null] {
  const [firstWord, ...rest] = title.trim().split(/\s+/)
  if (!rest.length) {
    return [title, null]
  }
  return [firstWord, rest.join(" ")]
}
