import type { ReactNode } from "react"
import { StudioSidebar } from "@/features/studio/shared/components/studio-sidebar"
import { StudioTopbar } from "@/features/studio/shared/components/studio-topbar"

export function StudioShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-secondary/25 text-foreground">
      <div className="flex min-h-screen">
        <StudioSidebar />
        <div className="min-w-0 flex-1 bg-background">
          <StudioTopbar />
          <main className="min-w-0 px-4 py-4 sm:px-6 lg:px-8">
            <div className="mx-auto w-full max-w-[1600px]">{children}</div>
          </main>
        </div>
      </div>
    </div>
  )
}
