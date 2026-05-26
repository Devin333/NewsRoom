import { cn } from "@/lib/utils"

export function SummaryCard({ label, value, compact = false }: { label: string; value: string | number; compact?: boolean }) {
  return (
    <div className={cn("rounded-2xl bg-[#edf1ee] p-4 dark:bg-secondary", compact && "flex min-h-[5.25rem] flex-col items-center justify-center text-center", !compact && "border border-border bg-background/60")}>
      <p className="text-xs text-[#334155]/55 dark:text-muted-foreground">{label}</p>
      <p className={cn("mt-1 font-black text-[#334155] dark:text-foreground", compact ? "text-2xl" : "text-2xl")}>{value}</p>
    </div>
  )
}
