import { cn } from "@/lib/utils"

export function SummaryCard({ label, value, compact = false }: { label: string; value: string | number; compact?: boolean }) {
  return (
    <div
      aria-label={`${label}: ${value}`}
      className={cn(
        "rounded-2xl bg-[#edf1ee] p-4 dark:bg-secondary",
        compact && "flex min-h-[4.5rem] flex-col justify-between rounded-xl bg-[#f3f6f3] px-3.5 py-3 text-left",
        !compact && "border border-border bg-background/60"
      )}
    >
      <p className={cn("text-xs text-[#334155]/55 dark:text-muted-foreground", compact && "text-[0.68rem] font-semibold uppercase tracking-[0.14em]")}>
        {label}
      </p>
      <p className={cn("mt-1 font-black text-[#334155] dark:text-foreground", compact ? "text-[1.7rem] leading-none" : "text-2xl")}>
        {value}
      </p>
    </div>
  )
}
