import { cn } from "@/lib/utils"

export function SummaryCard({ label, value, compact = false }: { label: string; value: string | number; compact?: boolean }) {
  return (
    <div
      aria-label={`${label}: ${value}`}
      className={cn(
        "rounded-xl bg-[#edf1ee] p-4 dark:bg-secondary",
        compact && "flex min-h-[4.25rem] flex-col justify-between rounded-lg bg-[#f5f7f4] px-3 py-2.5 text-left",
        !compact && "border border-border bg-background/60"
      )}
    >
      <p className={cn("text-xs text-[#334155]/55 dark:text-muted-foreground", compact && "text-[0.68rem] font-semibold uppercase tracking-[0.12em]")}>
        {label}
      </p>
      <p className={cn("mt-1 font-semibold text-[#1f2933] dark:text-foreground", compact ? "text-[1.45rem] leading-none" : "text-2xl")}>
        {value}
      </p>
    </div>
  )
}
