import { Columns3, LayoutList, Table2 } from "lucide-react"
import { cn } from "@/lib/utils"
import type { NewsViewMode } from "@/types/news"

const modes: Array<{ value: NewsViewMode; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { value: "card", label: "Cards", icon: LayoutList },
  { value: "dense", label: "Dense", icon: Columns3 },
  { value: "table", label: "Table", icon: Table2 },
]

export function NewsViewModeToggle({
  value,
  onChange,
}: {
  value: NewsViewMode
  onChange: (value: NewsViewMode) => void
}) {
  return (
    <div className="flex rounded-md border border-[#dbe3dc] bg-white p-1 dark:border-border dark:bg-card">
      {modes.map((mode) => {
        const Icon = mode.icon
        return (
          <button
            key={mode.value}
            type="button"
            onClick={() => onChange(mode.value)}
            className={cn(
              "flex h-8 items-center gap-2 rounded px-2 text-sm text-[#334155]/60 hover:text-[#334155] dark:text-muted-foreground dark:hover:text-foreground",
              value === mode.value && "bg-[#eef3ef] text-[#334155] dark:bg-secondary dark:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            <span className="hidden sm:inline">{mode.label}</span>
          </button>
        )
      })}
    </div>
  )
}
