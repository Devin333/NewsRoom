"use client"

import { useRef, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronDown, Menu } from "lucide-react"
import { AccountMenu } from "@/components/auth/account-menu"
import { MegaMenu } from "@/components/layout/MegaMenu"
import { PreferenceControls } from "@/components/layout/preference-controls"
import { SearchButton } from "@/components/layout/SearchButton"
import { Button } from "@/components/ui/button"
import { Sheet, SheetClose, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { NAVIGATION, type NavigationItem } from "@/config/navigation"
import { navigationLabel } from "@/lib/i18n/navigation"
import { useI18n } from "@/lib/i18n/use-i18n"
import { cn } from "@/lib/utils"
import type { LocaleMode } from "@/stores/ui-store"

export function AppHeader() {
  const pathname = usePathname()
  const { locale, t } = useI18n()
  const navRef = useRef<HTMLDivElement>(null)
  const [activeMenu, setActiveMenu] = useState<string | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [expandedMobileMenu, setExpandedMobileMenu] = useState<string | null>(NAVIGATION[0]?.label ?? null)
  const activeItem = NAVIGATION.find((item) => item.label === activeMenu)

  function closeDesktopMenu() {
    setActiveMenu(null)
  }

  function handleBlur(event: React.FocusEvent<HTMLDivElement>) {
    const nextFocus = event.relatedTarget

    if (nextFocus instanceof Node && event.currentTarget.contains(nextFocus)) {
      return
    }

    closeDesktopMenu()
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1480px] items-center gap-4 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2" aria-label={t("nav.home")}>
          <span className="flex size-6 items-center justify-center rounded-sm border-2 border-foreground text-xs font-black">
            N
          </span>
          <span className="text-base font-semibold tracking-normal">NewsRoom</span>
        </Link>

        <div
          ref={navRef}
          className="relative hidden flex-1 items-center justify-center lg:flex"
          onBlur={handleBlur}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              closeDesktopMenu()
            }
          }}
          onMouseLeave={closeDesktopMenu}
        >
          <nav className="flex items-center gap-6 text-sm text-muted-foreground" aria-label={t("nav.primary")}>
            {NAVIGATION.map((item) => (
              <DesktopNavItem
                key={item.label}
                item={item}
                locale={locale}
                active={isActive(pathname, item)}
                open={activeMenu === item.label}
                onOpen={() => setActiveMenu(item.label)}
              />
            ))}
          </nav>
          {activeItem ? <MegaMenu item={activeItem} /> : null}
        </div>

        <div className="min-w-0 flex-1 lg:hidden" />

        <SearchButton className="ml-auto hidden sm:inline-flex" />
        <PreferenceControls className="hidden md:flex" />
        <AccountMenu />

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="lg:hidden" aria-label={t("nav.mobile")}>
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent className="w-[min(22rem,88vw)] overflow-y-auto">
            <div className="mb-6 flex items-center gap-2 pr-8">
              <span className="flex size-7 items-center justify-center rounded-sm border-2 border-foreground text-xs font-black">
                N
              </span>
              <span className="text-base font-semibold">NewsRoom</span>
            </div>

            <nav className="space-y-2" aria-label={t("nav.mobile")}>
              {NAVIGATION.map((item) => {
                const expanded = expandedMobileMenu === item.label
                const groupId = `mobile-nav-${item.label.toLowerCase()}`
                const itemLabel = navigationLabel(item.label, locale)

                return (
                  <div key={item.label} className="rounded-md border border-border bg-background/60">
                    <div className="flex items-center gap-1">
                      <SheetClose asChild>
                        <Link
                          href={item.href}
                          className={cn(
                            "flex min-h-10 flex-1 items-center px-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                            isActive(pathname, item) && "text-foreground"
                          )}
                        >
                          {itemLabel}
                        </Link>
                      </SheetClose>
                      <button
                        type="button"
                        className="mr-1 flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label={`${expanded ? t("common.collapse") : t("common.expand")} ${itemLabel}`}
                        aria-expanded={expanded}
                        aria-controls={groupId}
                        onClick={() => setExpandedMobileMenu(expanded ? null : item.label)}
                      >
                        <ChevronDown className={cn("size-4 transition-transform", expanded && "rotate-180")} />
                      </button>
                    </div>

                    {expanded ? (
                      <div id={groupId} className="grid gap-1 border-t border-border p-2">
                        {item.children.map((child) => (
                          <SheetClose asChild key={`${item.label}-${child.label}`}>
                            <Link
                              href={child.href}
                              className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {navigationLabel(child.label, locale)}
                            </Link>
                          </SheetClose>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )
              })}

              <SheetClose asChild>
                <Link
                  href="/search"
                  className="flex min-h-10 items-center rounded-md border border-border bg-background/60 px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  {t("common.search")}
                </Link>
              </SheetClose>
              <div className="rounded-md border border-border bg-background/60 p-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-normal text-muted-foreground">
                  {t("common.display")}
                </p>
                <PreferenceControls />
              </div>
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  )
}

function DesktopNavItem({
  item,
  locale,
  active,
  open,
  onOpen
}: {
  item: NavigationItem
  locale: LocaleMode
  active: boolean
  open: boolean
  onOpen: () => void
}) {
  return (
    <Link
      href={item.href}
      className={cn(
        "border-b-2 border-transparent py-4 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:text-foreground",
        (active || open) && "border-foreground text-foreground"
      )}
      aria-expanded={open}
      onFocus={onOpen}
      onMouseEnter={onOpen}
    >
      {navigationLabel(item.label, locale)}
    </Link>
  )
}

function isActive(pathname: string, item: NavigationItem) {
  const hrefPath = item.href.split("?")[0].split("#")[0]

  if (hrefPath === "/") {
    return pathname === "/"
  }

  return pathname === hrefPath || pathname.startsWith(`${hrefPath}/`)
}
