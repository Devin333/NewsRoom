"use client"

import { studioEnvironment } from "@/features/studio/shared/lib/studio-navigation"

export function StudioTopbar() {
  const EnvironmentIcon = studioEnvironment.icon

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
      <div className="flex min-h-12 items-center justify-between gap-3 px-4 py-2 sm:px-6 lg:px-8">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold uppercase tracking-normal text-muted-foreground">NewsRoom Operations</p>
        </div>
        <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
          <EnvironmentIcon className="size-4 text-accent" />
          <span className="font-medium text-foreground">{studioEnvironment.label}</span>
          <span className="hidden sm:inline">{studioEnvironment.status}</span>
        </div>
      </div>
    </header>
  )
}
