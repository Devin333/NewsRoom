"use client"

import type { ComponentType } from "react"
import {
  BarChart3,
  Bot,
  CheckCircle2,
  Database,
  FileEdit,
  GitBranch,
  Layers3,
  Radio,
  Send,
  Settings,
  ShieldCheck
} from "lucide-react"
import { adminNavItems } from "@/features/admin/lib/mock-data"
import { pick, ui } from "@/features/admin/lib/i18n"
import type { AdminLang, AdminPage } from "@/features/admin/types"
import { cn } from "@/lib/utils"

const pageIcons = {
  overview: BarChart3,
  ingestion: Database,
  pipeline: GitBranch,
  review: ShieldCheck,
  content: FileEdit,
  topics: Layers3,
  sources: Radio,
  agents: Bot,
  gates: CheckCircle2,
  publishing: Send,
  settings: Settings
} satisfies Record<AdminPage, ComponentType<{ className?: string }>>

export function AdminSidebar({
  activePage,
  lang,
  onPageChange
}: {
  activePage: AdminPage
  lang: AdminLang
  onPageChange: (page: AdminPage) => void
}) {
  return (
    <aside className="border-border bg-card lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:w-72 lg:border-r">
      <div className="flex h-full flex-col">
        <div className="border-b border-border px-4 py-4">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border-2 border-foreground text-sm font-black">
              N
            </span>
            <div>
              <p className="text-base font-semibold text-foreground">NewsRoom</p>
              <p className="text-xs text-muted-foreground">{ui[lang].console}</p>
            </div>
          </div>
        </div>

        <nav className="flex gap-2 overflow-x-auto px-3 py-3 lg:block lg:flex-1 lg:space-y-1 lg:overflow-y-auto" aria-label={ui[lang].admin}>
          {adminNavItems.map((item) => {
            const Icon = pageIcons[item.id]
            const active = activePage === item.id

            return (
              <button
                key={item.id}
                type="button"
                className={cn(
                  "flex min-w-[12rem] items-center gap-3 rounded-md border border-transparent px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:min-w-0 lg:w-full",
                  active
                    ? "border-border bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                )}
                aria-current={active ? "page" : undefined}
                onClick={() => onPageChange(item.id)}
              >
                <Icon className="size-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{pick(item.label, lang)}</span>
                  <span className="block truncate text-xs text-muted-foreground">{pick(item.purpose, lang)}</span>
                </span>
              </button>
            )
          })}
        </nav>
      </div>
    </aside>
  )
}
