"use client"

import { useRef, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronDown, Menu } from "lucide-react"
import { NAVIGATION, type NavigationItem } from "@/config/navigation"
import { Button } from "@/components/ui/button"
import { Sheet, SheetClose, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { MegaMenu } from "@/components/layout/MegaMenu"
import { SearchButton } from "@/components/layout/SearchButton"
import { AccountMenu } from "@/components/auth/account-menu"
import { cn } from "@/lib/utils"

export function AppHeader() {
  const pathname = usePathname()
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
        <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="NewsRoom home">
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
          <nav className="flex items-center gap-6 text-sm text-muted-foreground" aria-label="Primary navigation">
            {NAVIGATION.map((item) => (
              <DesktopNavItem
                key={item.label}
                item={item}
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
        <AccountMenu />

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation menu">
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

            <nav className="space-y-2" aria-label="Mobile navigation">
              {NAVIGATION.map((item) => {
                const expanded = expandedMobileMenu === item.label
                const groupId = `mobile-nav-${item.label.toLowerCase()}`

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
                          {item.label}
                        </Link>
                      </SheetClose>
                      <button
                        type="button"
                        className="mr-1 flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label={`${expanded ? "Collapse" : "Expand"} ${item.label}`}
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
                              {child.label}
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
                  Search
                </Link>
              </SheetClose>
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  )
}

function DesktopNavItem({
  item,
  active,
  open,
  onOpen
}: {
  item: NavigationItem
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
      {item.label}
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
