"use client"

import type { ReactNode } from "react"
import { Topbar } from "@/components/layout/topbar"

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Topbar />
      <main className="min-w-0 px-4 py-6 sm:px-6">
        <div className="mx-auto w-full max-w-[1480px]">{children}</div>
      </main>
    </div>
  )
}
