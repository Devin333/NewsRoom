"use client"

import { useEffect, useState, type ReactNode } from "react"
import { RefreshCw, X } from "lucide-react"
import { PaperDetailContent, PaperDetailEyebrow } from "@/components/papers/shared/paper-detail-content"
import { translate } from "@/lib/i18n"
import { fetchPaperDetail } from "@/lib/papers/api"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Locale, Paper } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

const CLOSE_ANIMATION_MS = 420

export function PaperDetailDrawer({
  paper,
  paperId,
  locale,
  open,
  closeHref,
  onOpenChange
}: {
  paper: Paper | null
  paperId?: string | null
  locale: Locale
  open: boolean
  closeHref?: string
  onOpenChange: (open: boolean) => void
}) {
  const [activePaper, setActivePaper] = useState<Paper | null>(paper)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    if (paper) {
      if (!isPublicPaper(paper)) {
        setActivePaper(null)
        setDetailError("Paper detail is not available.")
        return
      }
      setActivePaper(paper)
      setDetailError(null)
      return
    }
    if (open && paperId) {
      return
    }

    const timeout = window.setTimeout(() => setActivePaper(null), CLOSE_ANIMATION_MS)
    return () => window.clearTimeout(timeout)
  }, [open, paper, paperId])

  useEffect(() => {
    if (!open || !paperId) {
      return
    }
    if (paper && (paper.id === paperId || paper.slug === paperId)) {
      return
    }

    let cancelled = false
    setActivePaper(null)
    setDetailError(null)
    fetchPaperDetail(paperId)
      .then((detail) => {
        if (!cancelled) {
          if (!isPublicPaper(detail)) {
            setActivePaper(null)
            setDetailError("Paper detail is not available.")
            return
          }
          setActivePaper(detail)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setDetailError(error instanceof Error ? error.message : "Paper detail request failed")
        }
      })
    return () => {
      cancelled = true
    }
  }, [open, paper, paperId])

  useEffect(() => {
    if (!open) {
      return
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onOpenChange(false)
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [onOpenChange, open])

  if (!activePaper && (!open || !paperId)) {
    return null
  }

  const isVisible = open && Boolean(activePaper || paperId)

  if (!activePaper) {
    return (
      <PaperDetailFrame
        isVisible={isVisible}
        locale={locale}
        closeHref={closeHref}
        eyebrow={translate(locale, "papers.reader.paper")}
        onOpenChange={onOpenChange}
      >
        <div className="min-h-0 flex-1 overflow-y-auto px-7 py-7">
          {detailError ? (
            <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
              {detailError}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-md border border-[#d8dfd8] bg-white px-4 py-4 text-sm text-[#334155]/68 dark:border-border dark:bg-card dark:text-muted-foreground">
              <RefreshCw className="size-4 animate-spin" />
              {translate(locale, "papers.reader.loading")}
            </div>
          )}
        </div>
      </PaperDetailFrame>
    )
  }

  return (
    <PaperDetailFrame
      isVisible={isVisible}
      locale={locale}
      closeHref={closeHref}
      eyebrow={<PaperDetailEyebrow paper={activePaper} locale={locale} />}
      onOpenChange={onOpenChange}
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-7 py-7">
        <PaperDetailContent paper={activePaper} locale={locale} detailError={detailError} titleLevel={2} />
      </div>
    </PaperDetailFrame>
  )
}

function isPublicPaper(paper: Paper) {
  return paper.isPublished !== false
}

function PaperDetailFrame({
  children,
  closeHref,
  eyebrow,
  isVisible,
  locale,
  onOpenChange
}: {
  children: ReactNode
  closeHref?: string
  eyebrow: ReactNode
  isVisible: boolean
  locale: Locale
  onOpenChange: (open: boolean) => void
}) {
  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-50 bg-[#0f172a]/25 backdrop-blur-sm transition-[opacity,backdrop-filter] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]",
          isVisible ? "opacity-100" : "pointer-events-none opacity-0 backdrop-blur-0"
        )}
        aria-hidden="true"
        onClick={() => onOpenChange(false)}
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-[min(58rem,96vw)] flex-col border-l border-[#d8dfd8] bg-[#f7f9f6] shadow-[-24px_0_70px_rgba(15,23,42,0.18)] transition-[transform,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] dark:border-border dark:bg-background xl:w-[min(76rem,72vw)] 2xl:w-[clamp(72rem,73vw,94rem)]",
          isVisible ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-full opacity-0"
        )}
        aria-label="Paper detail"
        aria-modal="true"
        role="dialog"
      >
        <div className="flex items-center justify-between border-b border-[#d8dfd8] px-7 py-5 dark:border-border">
          <div className="text-xs uppercase tracking-[0.16em] text-[#334155]/55">{eyebrow}</div>
          <a
            href={closeHref ?? "/papers"}
            role="button"
            className="rounded-full p-2 text-[#334155]/55 transition-colors hover:bg-white hover:text-[#334155] dark:hover:bg-card dark:hover:text-foreground"
            aria-label={t(papersCopy.dismiss, locale)}
            onClick={(event) => {
              event.preventDefault()
              onOpenChange(false)
            }}
          >
            <X className="size-5" />
          </a>
        </div>

        {children}
      </aside>
    </>
  )
}
