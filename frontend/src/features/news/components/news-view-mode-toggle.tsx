import { Columns3, LayoutList, Table2 } from "lucide-react"
import { cn } from "@/lib/utils"
import type { NewsViewMode } from "@/types/news"

const modes: Array<{ value: NewsViewMode; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { value: "card", label: "卡片", icon: LayoutList },
  { value: "dense", label: "紧凑", icon: Columns3 },
  { value: "table", label: "表格", icon: Table2 }
]

export function NewsViewModeToggle({
  value,
  onChange
}: {
  value: NewsViewMode
  onChange: (value: NewsViewMode) => void
}) {
  return (
    <div className="flex rounded-md border border-border bg-card p-1">
      {modes.map((mode) => {
        const Icon = mode.icon
        return (
          <button
            key={mode.value}
            type="button"
            onClick={() => onChange(mode.value)}
            className={cn(
              "flex h-8 items-center gap-2 rounded px-2 text-sm text-muted-foreground hover:text-foreground",
              value === mode.value && "bg-secondary text-foreground"
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
