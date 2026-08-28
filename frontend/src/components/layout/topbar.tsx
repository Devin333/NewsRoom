"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Bell, Command, Moon, Search, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useI18n } from "@/lib/i18n/use-i18n"
import { cn } from "@/lib/utils"
import { useUiStore } from "@/stores/ui-store"

export function Topbar() {
  const { t } = useI18n()
  const pathname = usePathname()
  const setCommandOpen = useUiStore((state) => state.setCommandOpen)
  const theme = useUiStore((state) => state.theme)
  const toggleTheme = useUiStore((state) => state.toggleTheme)
  const ThemeIcon = theme === "dark" ? Sun : Moon

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1480px] items-center gap-5 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-sm border-2 border-foreground text-xs font-black">A</span>
          <span className="text-base font-semibold tracking-normal">Agora Hub</span>
          <span className="hidden font-serif text-sm italic text-muted-foreground sm:inline">{t("portal.topbar.withEvidence")}</span>
        </Link>

        <nav className="hidden items-center gap-5 text-sm text-muted-foreground lg:flex">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "border-b-2 border-transparent py-4 transition-colors hover:text-foreground",
                isActive(pathname, item.href) && "border-foreground text-foreground"
              )}
            >
              {t(item.labelKey)}
            </Link>
          ))}
        </nav>

        <div className="min-w-0 flex-1" />

        <Button variant="outline" size="sm" className="hidden md:inline-flex">
          {t("portal.topbar.feedback")}
        </Button>

        <div className="relative hidden min-w-0 sm:block sm:w-64 xl:w-80">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-9 border-border bg-background pl-9 pr-12" placeholder={t("portal.topbar.searchPlaceholder")} />
          <span className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-border bg-card px-1.5 py-0.5 text-[10px] text-muted-foreground xl:inline">
            Ctrl K
          </span>
        </div>

        <Button variant="outline" size="sm" className="hidden gap-2 md:inline-flex" onClick={() => setCommandOpen(true)}>
          <Command className="size-4" />
          {t("portal.topbar.command")}
        </Button>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("portal.topbar.notifications")}>
              <Bell className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("portal.topbar.notificationPlaceholder")}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label={theme === "dark" ? "切换浅色主题" : "切换深色主题"}>
              <ThemeIcon className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{theme === "dark" ? "切换浅色主题" : "切换深色主题"}</TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}

const navItems = [
  { href: "/", labelKey: "nav.trends" },
  { href: "/news", labelKey: "nav.today" },
  { href: "/topics", labelKey: "nav.topics" },
  { href: "/tech", labelKey: "nav.engineering" },
  { href: "/reports", labelKey: "nav.reports" },
  { href: "/studio", labelKey: "nav.studio" }
]

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`)
}
