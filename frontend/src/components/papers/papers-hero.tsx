import { SummaryCard } from "@/components/papers/summary-card"
import { cn } from "@/lib/utils"

export function PapersHero({
  eyebrow,
  title,
  subtitle,
  stats,
  variant = "default"
}: {
  eyebrow?: string
  title: string
  subtitle: string
  stats: Array<{ label: string; value: string | number }>
  variant?: "default" | "editorial"
}) {
  if (variant === "editorial") {
    const [firstWord, ...rest] = title.split(" ")
    return (
      <section className="grid gap-8 py-12 lg:grid-cols-[1fr_20rem] lg:items-end">
        <div>
          {eyebrow ? (
            <p className="mb-5 text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
              {eyebrow}
            </p>
          ) : null}
          <h1 className="max-w-4xl text-5xl font-black leading-none tracking-normal text-[#111827] sm:text-6xl lg:text-7xl dark:text-foreground">
            {firstWord}{" "}
            <span className="bg-gradient-to-r from-emerald-600 via-teal-600 to-blue-600 bg-clip-text text-transparent">
              {rest.join(" ")}
            </span>
          </h1>
          <p className="mt-6 max-w-3xl text-base leading-7 text-slate-600 dark:text-muted-foreground">{subtitle}</p>
        </div>
        <div className="rounded-3xl border border-[#dbe3dc] bg-white/85 p-5 shadow-[0_24px_60px_rgba(15,23,42,0.10)] dark:border-border dark:bg-card">
          <div className="grid grid-cols-3 gap-3">
            {stats.map((stat) => (
              <SummaryCard key={stat.label} label={stat.label} value={stat.value} compact />
            ))}
          </div>
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
