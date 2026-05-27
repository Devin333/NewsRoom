"use client"

import type { ReactNode } from "react"
import { usePathname } from "next/navigation"
import { ResearchHeader } from "@/components/layout/research-header"
import type { FrontendSurface } from "@/lib/frontend-surface"
import { useUiStore } from "@/stores/ui-store"
import { cn } from "@/lib/utils"

export function AppShell({ children, surface = "portal" }: { children: ReactNode; surface?: FrontendSurface }) {
  const pathname = usePathname()
  const theme = useUiStore((state) => state.theme)
  const locale = useUiStore((state) => state.locale)
  const setTheme = useUiStore((state) => state.setTheme)
  const setLocale = useUiStore((state) => state.setLocale)

  if (surface === "admin") {
    return <div className="min-h-screen bg-background text-foreground">{children}</div>
  }

  if (pathname.startsWith("/admin") || pathname.startsWith("/studio")) {
    return <div className="min-h-screen bg-background text-foreground">{children}</div>
  }

  const isPortalHomeRoute = pathname === "/"
  const isReaderRoute = isPaperReaderRoute(pathname)
  const usesResearchFrame = pathname.startsWith("/papers") || isPortalHomeRoute

  if (isReaderRoute) {
    return <div className="min-h-screen bg-background text-foreground">{children}</div>
  }

  return (
    <div className={cn("min-h-screen text-foreground", usesResearchFrame ? "font-papers-research bg-[#f7f9f6] dark:bg-background" : "bg-background")}>
      <ResearchHeader locale={locale} theme={theme} onLocaleChange={setLocale} onThemeChange={setTheme} />
      <main className={cn("min-w-0", usesResearchFrame ? "px-5 pb-16 pt-0 sm:px-8 2xl:px-12" : "px-4 py-6 sm:px-6")}>
        <div className={cn("mx-auto w-full", usesResearchFrame ? "max-w-[1920px]" : "max-w-[1480px]")}>{children}</div>
      </main>
    </div>
  )
}

function isPaperReaderRoute(pathname: string) {
  const parts = pathname.split("/").filter(Boolean)
  return parts.length === 2 && parts[0] === "papers"
}
