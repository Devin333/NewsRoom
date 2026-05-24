"use client"

import { useRef, useState } from "react"
import Link from "next/link"
import { ChevronDown, Menu, Search } from "lucide-react"
import { PapersDropdown } from "@/components/papers/papers-dropdown"
import { PapersLanguageToggle } from "@/components/papers/shared/language-toggle"
import { PapersThemeToggle } from "@/components/papers/shared/theme-toggle"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetClose, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { papersCopy, t } from "@/lib/papers/copy"
import { papersDropdownItems } from "@/lib/papers/routes"
import type { Locale } from "@/lib/papers/types"
import type { ThemeMode } from "@/stores/ui-store"

export function PapersHeader({
  locale,
  theme,
  onLocaleChange,
  onThemeChange
}: {
  locale: Locale
  theme: ThemeMode
  onLocaleChange: (locale: Locale) => void
  onThemeChange: (theme: ThemeMode) => void
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  function handleBlur(event: React.FocusEvent<HTMLDivElement>) {
    const nextFocus = event.relatedTarget
    if (nextFocus instanceof Node && event.currentTarget.contains(nextFocus)) {
      return
    }
    setDropdownOpen(false)
  }

  return (
    <header className="sticky top-0 z-40 border-b border-[#dfe5df] bg-white/90 backdrop-blur dark:border-border dark:bg-card/95">
      <div className="mx-auto flex min-h-[64px] max-w-[1920px] items-center gap-5 px-0 py-2">
        <Link href="/papers" className="flex shrink-0 items-center gap-3" aria-label="NewsRoom Research">
          <span className="flex size-9 items-center justify-center rounded-full bg-[#0f172a] text-sm font-black text-white">
            N
          </span>
          <span>
            <span className="block text-base font-semibold leading-5">
              NewsRoom <span className="text-emerald-600">Research</span>
            </span>
            <span className="block text-xs text-[#334155]/55 dark:text-muted-foreground">{t(papersCopy.brandSubline, locale)}</span>
          </span>
        </Link>

        <div
          ref={wrapperRef}
          className="relative hidden flex-1 items-center justify-start lg:flex"
          onBlur={handleBlur}
          onMouseLeave={() => setDropdownOpen(false)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setDropdownOpen(false)
            }
          }}
        >
          <button
            type="button"
            className="inline-flex h-9 items-center gap-1 rounded-full bg-[#eef3ef] px-4 text-sm font-medium text-[#334155] transition-colors hover:bg-[#e3ece5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:bg-secondary dark:text-foreground"
            aria-expanded={dropdownOpen}
            onFocus={() => setDropdownOpen(true)}
            onMouseEnter={() => setDropdownOpen(true)}
          >
            {t(papersCopy.papersNav, locale)}
            <ChevronDown className="size-4" />
          </button>
          {dropdownOpen ? <PapersDropdown locale={locale} /> : null}
        </div>

        <div className="relative ml-auto hidden w-[min(26rem,32vw)] md:block">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-10 rounded-full border-[#d7dfd8] bg-white pl-9 shadow-sm dark:border-border dark:bg-card" placeholder={t(papersCopy.searchPlaceholder, locale)} />
        </div>
        <PapersThemeToggle theme={theme} locale={locale} onThemeChange={onThemeChange} />
        <PapersLanguageToggle locale={locale} onLocaleChange={onLocaleChange} />

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button type="button" variant="ghost" size="icon" className="lg:hidden" aria-label={t(papersCopy.openNavigation, locale)}>
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent className="w-[min(22rem,88vw)] overflow-y-auto">
            <div className="mb-6 pr-8">
              <p className="text-sm font-semibold">{t(papersCopy.brand, locale)}</p>
              <p className="text-xs text-muted-foreground">{t(papersCopy.brandSubline, locale)}</p>
            </div>
            <div className="relative mb-4">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="h-9 pl-9" placeholder={t(papersCopy.searchPlaceholder, locale)} />
            </div>
            <nav className="space-y-2" aria-label="Papers mobile navigation">
              {papersDropdownItems.map((item) => (
                <SheetClose asChild key={item.href}>
                  <Link
                    href={item.href}
                    className="block rounded-md border border-border bg-background/60 px-3 py-2 text-sm transition-colors hover:bg-secondary"
                  >
                    <span className="font-medium">{t(papersCopy[item.labelKey], locale)}</span>
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                      {t(papersCopy[item.descriptionKey], locale)}
                    </span>
                  </Link>
                </SheetClose>
              ))}
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  )
}
