"use client"

import type { ReactNode } from "react"
import { usePathname } from "next/navigation"
import { PapersHeader } from "@/components/papers/papers-header"
import { AppHeader } from "@/components/layout/AppHeader"
import { useUiStore } from "@/stores/ui-store"
import { cn } from "@/lib/utils"

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const theme = useUiStore((state) => state.theme)
  const locale = useUiStore((state) => state.locale)
  const setTheme = useUiStore((state) => state.setTheme)
  const setLocale = useUiStore((state) => state.setLocale)

  if (pathname.startsWith("/admin")) {
    return <div className="min-h-screen bg-background text-foreground">{children}</div>
  }

  const isPapersRoute = pathname.startsWith("/papers")

  return (
    <div className={cn("min-h-screen text-foreground", isPapersRoute ? "font-papers-research bg-[#f7f9f6] dark:bg-background" : "bg-background")}>
      {isPapersRoute ? (
        <PapersHeader locale={locale} theme={theme} onLocaleChange={setLocale} onThemeChange={setTheme} />
      ) : (
        <AppHeader />
      )}
      <main className={cn("min-w-0", isPapersRoute ? "px-5 pb-16 pt-0 sm:px-8 2xl:px-12" : "px-4 py-6 sm:px-6")}>
        <div className={cn("mx-auto w-full", isPapersRoute ? "max-w-[1920px]" : "max-w-[1480px]")}>{children}</div>
      </main>
    </div>
  )
}
