"use client"

import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react"
import { ChevronLeft, ChevronRight, FileWarning, Loader2, Search, ZoomIn, ZoomOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { Locale } from "@/lib/papers/types"

type PaperPdfViewerProps = {
  pdfUrl: string
  title: string
  locale: Locale
  fallback: ReactNode
  initialPage?: number
  onPageChange?: (pageNumber: number, numPages: number) => void
}

type PdfViewport = {
  width: number
  height: number
}

type PdfRenderTask = {
  promise: Promise<void>
  cancel: () => void
}

type PdfPage = {
  getTextContent?: () => Promise<PdfTextContent>
  getViewport: (options: { scale: number }) => PdfViewport
  render: (params: { canvasContext: CanvasRenderingContext2D; viewport: PdfViewport }) => PdfRenderTask
}

type PdfDocument = {
  numPages: number
  getPage: (pageNumber: number) => Promise<PdfPage>
  destroy: () => Promise<void> | void
}

type PdfLoadingTask = {
  promise: Promise<PdfDocument>
  destroy: () => Promise<void> | void
}

type PdfTextContent = {
  items: Array<{ str?: string }>
}

type PdfPageText = {
  pageNumber: number
  text: string
}

type PdfSearchResult = {
  id: string
  pageNumber: number
  snippet: string
  matchIndex: number
}

const MIN_SCALE = 0.75
const MAX_SCALE = 2
const SCALE_STEP = 0.25
const THUMBNAIL_WIDTH = 88
const MIN_SEARCH_LENGTH = 2

export function PaperPdfViewer({
  pdfUrl,
  title,
  locale,
  fallback,
  initialPage,
  onPageChange,
}: PaperPdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const renderTaskRef = useRef<PdfRenderTask | null>(null)
  const initialPageRef = useRef(initialPage)
  const initialPageAppliedRef = useRef(false)
  const userNavigatedRef = useRef(false)
  const [pdfDocument, setPdfDocument] = useState<PdfDocument | null>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const [isRendering, setIsRendering] = useState(false)
  const [pageNumber, setPageNumber] = useState(1)
  const [pageInput, setPageInput] = useState("1")
  const [numPages, setNumPages] = useState(0)
  const [scale, setScale] = useState(1)
  const [pageTexts, setPageTexts] = useState<PdfPageText[]>([])
  const [searchQuery, setSearchQuery] = useState("")
  const [searchStatus, setSearchStatus] = useState<"idle" | "indexing" | "ready" | "error">("idle")
  const [activeSearchIndex, setActiveSearchIndex] = useState(0)
  const searchResults = useMemo(() => buildSearchResults(pageTexts, searchQuery), [pageTexts, searchQuery])

  useEffect(() => {
    initialPageRef.current = initialPage
  }, [initialPage])

  useEffect(() => {
    let cancelled = false
    let loadedDocument: PdfDocument | null = null
    let loadingTask: PdfLoadingTask | null = null

    setStatus("loading")
    setIsRendering(false)
    setPdfDocument(null)
    setNumPages(0)
    setPageNumber(1)
    setPageInput("1")
    setScale(1)
    setPageTexts([])
    setSearchQuery("")
    setSearchStatus("idle")
    setActiveSearchIndex(0)
    initialPageAppliedRef.current = false
    userNavigatedRef.current = false
    renderTaskRef.current?.cancel()
    renderTaskRef.current = null

    async function loadPdf() {
      try {
        const pdfjs = await import("pdfjs-dist")
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs"
        loadingTask = pdfjs.getDocument({
          disableAutoFetch: true,
          disableStream: true,
          rangeChunkSize: 65536,
          url: pdfProxyUrl(pdfUrl),
          withCredentials: false,
        }) as unknown as PdfLoadingTask
        const pdf = await loadingTask.promise
        loadedDocument = pdf
        if (cancelled) {
          await pdf.destroy()
          return
        }
        const firstPage = clampPage(initialPageRef.current ?? 1, pdf.numPages)
        setPdfDocument(pdf)
        setNumPages(pdf.numPages)
        setPageNumber(firstPage)
        setPageInput(String(firstPage))
        initialPageAppliedRef.current = initialPageRef.current !== undefined
        setStatus("ready")
      } catch {
        if (!cancelled) {
          setStatus("error")
        }
      }
    }

    void loadPdf()

    return () => {
      cancelled = true
      renderTaskRef.current?.cancel()
      renderTaskRef.current = null
      void loadingTask?.destroy()
      void loadedDocument?.destroy()
    }
  }, [pdfUrl])

  useEffect(() => {
    if (!pdfDocument || status !== "ready" || numPages <= 0) {
      return
    }

    let cancelled = false
    setSearchStatus("indexing")
    setPageTexts([])

    async function indexPdfText() {
      try {
        const indexedPages: PdfPageText[] = []
        for (let index = 1; index <= numPages; index += 1) {
          const page = await pdfDocument!.getPage(index)
          if (!page.getTextContent) {
            throw new Error("PDF text content unavailable")
          }
          const content = await page.getTextContent()
          if (cancelled) {
            return
          }
          indexedPages.push({
            pageNumber: index,
            text: content.items.map((item) => item.str ?? "").filter(Boolean).join(" "),
          })
        }
        if (!cancelled) {
          setPageTexts(indexedPages)
          setSearchStatus("ready")
        }
      } catch {
        if (!cancelled) {
          setPageTexts([])
          setSearchStatus("error")
        }
      }
    }

    void indexPdfText()

    return () => {
      cancelled = true
    }
  }, [numPages, pdfDocument, status])

  useEffect(() => {
    if (
      initialPage === undefined ||
      initialPageAppliedRef.current ||
      userNavigatedRef.current ||
      status !== "ready" ||
      !pdfDocument ||
      numPages <= 0
    ) {
      return
    }
    const firstPage = clampPage(initialPage, numPages)
    setPageNumber(firstPage)
    setPageInput(String(firstPage))
    initialPageAppliedRef.current = true
  }, [initialPage, numPages, pdfDocument, status])

  useEffect(() => {
    if (!pdfDocument || status !== "ready") {
      return
    }

    let cancelled = false
    renderTaskRef.current?.cancel()
    renderTaskRef.current = null

    async function renderPage() {
      setIsRendering(true)
      try {
        const page = await pdfDocument!.getPage(pageNumber)
        if (cancelled) {
          return
        }
        const viewport = page.getViewport({ scale })
        const canvas = canvasRef.current
        const context = canvas?.getContext("2d")
        if (!canvas || !context) {
          throw new Error("PDF canvas context unavailable")
        }
        const outputScale = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1
        canvas.width = Math.floor(viewport.width * outputScale)
        canvas.height = Math.floor(viewport.height * outputScale)
        canvas.style.width = `${Math.floor(viewport.width)}px`
        canvas.style.height = `${Math.floor(viewport.height)}px`
        context.setTransform(outputScale, 0, 0, outputScale, 0, 0)
        const renderTask = page.render({ canvasContext: context, viewport })
        renderTaskRef.current = renderTask
        await renderTask.promise
      } catch {
        if (!cancelled) {
          setStatus("error")
        }
      } finally {
        if (!cancelled) {
          setIsRendering(false)
        }
      }
    }

    void renderPage()

    return () => {
      cancelled = true
      renderTaskRef.current?.cancel()
      renderTaskRef.current = null
    }
  }, [pageNumber, pdfDocument, scale, status])

  useEffect(() => {
    if (status === "ready" && numPages > 0) {
      onPageChange?.(pageNumber, numPages)
    }
  }, [numPages, onPageChange, pageNumber, status])

  useEffect(() => {
    setActiveSearchIndex((current) => clampSearchIndex(current, searchResults.length))
  }, [searchResults.length])

  if (status === "error") {
    return (
      <div className="min-h-[42rem]">
        <div className="border-b border-[#d8dfd8] bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-border dark:bg-amber-950/30 dark:text-amber-100">
          <div className="flex items-center gap-2 font-semibold">
            <FileWarning className="size-4" />
            {locale === "zh" ? "PDF could not be rendered; showing text fallback." : "PDF could not be rendered; showing text fallback."}
          </div>
        </div>
        {fallback}
      </div>
    )
  }

  const canGoPrevious = status === "ready" && pageNumber > 1
  const canGoNext = status === "ready" && numPages > 0 && pageNumber < numPages
  const canZoomOut = status === "ready" && scale > MIN_SCALE
  const canZoomIn = status === "ready" && scale < MAX_SCALE

  function goToPage(nextPage: number, options: { userInitiated?: boolean } = {}) {
    if (options.userInitiated !== false) {
      userNavigatedRef.current = true
    }
    const clamped = clampPage(nextPage, numPages)
    setPageNumber(clamped)
    setPageInput(String(clamped))
  }

  function handlePageSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    goToPage(Number.parseInt(pageInput, 10))
  }

  function changeScale(nextScale: number) {
    userNavigatedRef.current = true
    setScale(clampScale(nextScale))
  }

  function goToSearchResult(nextIndex: number) {
    if (!searchResults.length) {
      return
    }
    const clamped = clampSearchIndex(nextIndex, searchResults.length)
    setActiveSearchIndex(clamped)
    goToPage(searchResults[clamped].pageNumber)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (status !== "ready") {
      return
    }
    const target = event.target
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement
    ) {
      return
    }
    if (event.key === "ArrowLeft" || event.key === "PageUp") {
      event.preventDefault()
      goToPage(pageNumber - 1)
    } else if (event.key === "ArrowRight" || event.key === "PageDown") {
      event.preventDefault()
      goToPage(pageNumber + 1)
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault()
      changeScale(scale + SCALE_STEP)
    } else if (event.key === "-" || event.key === "_") {
      event.preventDefault()
      changeScale(scale - SCALE_STEP)
    }
  }

  return (
    <div
      aria-label={`${title} PDF viewer`}
      className="flex min-h-[42rem] flex-col bg-[#f8faf9] outline-none focus-visible:ring-2 focus-visible:ring-[#315d8a]/35 dark:bg-background"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className="flex flex-col gap-3 border-b border-[#d8dfd8] bg-white px-4 py-3 dark:border-border dark:bg-card lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-[#334155] dark:text-foreground">{title}</h2>
          <p className="mt-1 text-xs text-[#334155]/55 dark:text-muted-foreground">
            {status === "ready" ? `Page ${pageNumber} of ${numPages}` : locale === "zh" ? "Loading PDF" : "Loading PDF"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Previous page"
            disabled={!canGoPrevious}
            onClick={() => goToPage(pageNumber - 1)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <form className="flex items-center gap-2" onSubmit={handlePageSubmit}>
            <Input
              aria-label="Page number"
              className="h-9 w-20 bg-white text-center dark:bg-background"
              disabled={status !== "ready"}
              min={1}
              max={numPages || 1}
              type="number"
              value={pageInput}
              onChange={(event) => setPageInput(event.target.value)}
            />
            <span className="text-xs text-[#334155]/55 dark:text-muted-foreground">/ {numPages || "-"}</span>
          </form>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Next page"
            disabled={!canGoNext}
            onClick={() => goToPage(pageNumber + 1)}
          >
            <ChevronRight className="size-4" />
          </Button>
          <span className="mx-1 h-6 w-px bg-[#d8dfd8] dark:bg-border" />
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Zoom out"
            disabled={!canZoomOut}
            onClick={() => changeScale(scale - SCALE_STEP)}
          >
            <ZoomOut className="size-4" />
          </Button>
          <span className="w-14 text-center text-xs font-semibold text-[#334155]/70 dark:text-muted-foreground">
            {Math.round(scale * 100)}%
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Zoom in"
            disabled={!canZoomIn}
            onClick={() => changeScale(scale + SCALE_STEP)}
          >
            <ZoomIn className="size-4" />
          </Button>
        </div>
      </div>
      <PdfSearchPanel
        activeIndex={activeSearchIndex}
        locale={locale}
        onQueryChange={(nextQuery) => {
          setSearchQuery(nextQuery)
          setActiveSearchIndex(0)
        }}
        onSelectResult={goToSearchResult}
        query={searchQuery}
        results={searchResults}
        searchStatus={searchStatus}
      />

      <div className="grid min-h-[38rem] flex-1 lg:grid-cols-[7.25rem_minmax(0,1fr)]">
        <PdfThumbnailRail
          currentPage={pageNumber}
          locale={locale}
          numPages={numPages}
          onSelectPage={(nextPage) => goToPage(nextPage)}
          pdfDocument={pdfDocument}
          status={status}
          title={title}
        />
        <div className="relative flex h-[78vh] min-h-[38rem] flex-1 justify-center overflow-auto bg-[#eef4ef] p-4 dark:bg-secondary/30">
          {status === "loading" ? (
            <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-background/80">
              <div className="inline-flex items-center gap-2 rounded-md border border-[#d8dfd8] bg-white px-4 py-3 text-sm font-semibold text-[#334155]/70 shadow-sm dark:border-border dark:bg-card dark:text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                {locale === "zh" ? "Loading PDF" : "Loading PDF"}
              </div>
            </div>
          ) : null}
          {isRendering && status === "ready" ? (
            <div className="absolute right-4 top-4 inline-flex items-center gap-2 rounded-md bg-white px-3 py-2 text-xs font-semibold text-[#334155]/65 shadow-sm dark:bg-card dark:text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              {locale === "zh" ? "Rendering" : "Rendering"}
            </div>
          ) : null}
          <canvas
            ref={canvasRef}
            aria-label={`${title} PDF page ${pageNumber}`}
            className="block self-start bg-white shadow-lg"
          />
        </div>
      </div>
    </div>
  )
}

function PdfSearchPanel({
  activeIndex,
  locale,
  onQueryChange,
  onSelectResult,
  query,
  results,
  searchStatus,
}: {
  activeIndex: number
  locale: Locale
  onQueryChange: (query: string) => void
  onSelectResult: (index: number) => void
  query: string
  results: PdfSearchResult[]
  searchStatus: "idle" | "indexing" | "ready" | "error"
}) {
  const trimmedQuery = query.trim()
  const queryTooShort = trimmedQuery.length > 0 && trimmedQuery.length < MIN_SEARCH_LENGTH
  const canUseResults = results.length > 0
  const statusText =
    searchStatus === "indexing"
      ? "Indexing PDF text"
      : searchStatus === "error"
        ? "PDF search text is unavailable."
        : queryTooShort
          ? "Enter at least 2 characters."
          : trimmedQuery.length >= MIN_SEARCH_LENGTH
            ? `${results.length} result${results.length === 1 ? "" : "s"}`
            : "Search this PDF"

  return (
    <section className="border-b border-[#d8dfd8] bg-white px-4 py-3 dark:border-border dark:bg-card">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <label className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#334155]/45" />
          <Input
            aria-label="Search PDF text"
            className="h-9 bg-white pl-9 dark:bg-background"
            disabled={searchStatus === "indexing"}
            placeholder={locale === "zh" ? "Search PDF" : "Search PDF"}
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
          />
        </label>
        <div className="flex items-center gap-2">
          <span className="min-w-36 text-xs font-semibold text-[#334155]/58 dark:text-muted-foreground">
            {statusText}
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Previous search result"
            disabled={!canUseResults || activeIndex <= 0}
            onClick={() => onSelectResult(activeIndex - 1)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Next search result"
            disabled={!canUseResults || activeIndex >= results.length - 1}
            onClick={() => onSelectResult(activeIndex + 1)}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
      {canUseResults ? (
        <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
          {results.map((result, index) => (
            <button
              key={result.id}
              type="button"
              aria-current={index === activeIndex ? "true" : undefined}
              className={[
                "min-w-56 max-w-72 rounded-md border px-3 py-2 text-left text-xs leading-5 transition",
                index === activeIndex
                  ? "border-[#315d8a] bg-[#eef4ef] text-[#334155] ring-2 ring-[#315d8a]/20 dark:bg-secondary dark:text-foreground"
                  : "border-[#d8dfd8] bg-white text-[#334155]/68 hover:border-[#315d8a]/60 dark:border-border dark:bg-background dark:text-muted-foreground",
              ].join(" ")}
              onClick={() => onSelectResult(index)}
            >
              <span className="block font-semibold text-[#334155] dark:text-foreground">
                Page {result.pageNumber}
              </span>
              <span className="line-clamp-2">{result.snippet}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function PdfThumbnailRail({
  currentPage,
  locale,
  numPages,
  onSelectPage,
  pdfDocument,
  status,
  title,
}: {
  currentPage: number
  locale: Locale
  numPages: number
  onSelectPage: (pageNumber: number) => void
  pdfDocument: PdfDocument | null
  status: "loading" | "ready" | "error"
  title: string
}) {
  if (status !== "ready" || !pdfDocument || numPages <= 0) {
    return (
      <aside className="hidden border-r border-[#d8dfd8] bg-white p-3 dark:border-border dark:bg-card lg:block">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/45 dark:text-muted-foreground">
          {locale === "zh" ? "Pages" : "Pages"}
        </p>
      </aside>
    )
  }

  return (
    <aside className="hidden max-h-[78vh] overflow-y-auto border-r border-[#d8dfd8] bg-white p-3 dark:border-border dark:bg-card lg:block">
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/45 dark:text-muted-foreground">
        {locale === "zh" ? "Pages" : "Pages"}
      </p>
      <div className="space-y-2">
        {Array.from({ length: numPages }, (_, index) => {
          const thumbnailPage = index + 1
          return (
            <PdfThumbnailButton
              key={thumbnailPage}
              active={thumbnailPage === currentPage}
              onSelect={() => onSelectPage(thumbnailPage)}
              pageNumber={thumbnailPage}
              pdfDocument={pdfDocument}
              title={title}
            />
          )
        })}
      </div>
    </aside>
  )
}

function PdfThumbnailButton({
  active,
  onSelect,
  pageNumber,
  pdfDocument,
  title,
}: {
  active: boolean
  onSelect: () => void
  pageNumber: number
  pdfDocument: PdfDocument
  title: string
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const renderTaskRef = useRef<PdfRenderTask | null>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")

  useEffect(() => {
    let cancelled = false
    renderTaskRef.current?.cancel()
    renderTaskRef.current = null
    setStatus("loading")

    async function renderThumbnail() {
      try {
        const page = await pdfDocument.getPage(pageNumber)
        if (cancelled) {
          return
        }
        const viewport = page.getViewport({ scale: 1 })
        const thumbnailScale = THUMBNAIL_WIDTH / Math.max(viewport.width, 1)
        const thumbnailViewport = page.getViewport({ scale: thumbnailScale })
        const canvas = canvasRef.current
        const context = canvas?.getContext("2d")
        if (!canvas || !context) {
          throw new Error("thumbnail canvas context unavailable")
        }
        canvas.width = Math.floor(thumbnailViewport.width)
        canvas.height = Math.floor(thumbnailViewport.height)
        canvas.style.width = `${Math.floor(thumbnailViewport.width)}px`
        canvas.style.height = `${Math.floor(thumbnailViewport.height)}px`
        const renderTask = page.render({ canvasContext: context, viewport: thumbnailViewport })
        renderTaskRef.current = renderTask
        await renderTask.promise
        if (!cancelled) {
          setStatus("ready")
        }
      } catch {
        if (!cancelled) {
          setStatus("error")
        }
      }
    }

    void renderThumbnail()

    return () => {
      cancelled = true
      renderTaskRef.current?.cancel()
      renderTaskRef.current = null
    }
  }, [pageNumber, pdfDocument])

  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      aria-label={`Go to page ${pageNumber}`}
      className={[
        "block w-full rounded-md border p-1 text-left text-xs transition",
        active
          ? "border-[#315d8a] bg-[#eef4ef] shadow-sm ring-2 ring-[#315d8a]/25 dark:bg-secondary"
          : "border-[#d8dfd8] bg-white hover:border-[#315d8a]/60 dark:border-border dark:bg-background",
      ].join(" ")}
      onClick={onSelect}
    >
      <span className="flex min-h-28 items-center justify-center rounded-sm bg-[#eef4ef] dark:bg-secondary/60">
        {status === "error" ? (
          <span className="px-2 text-center text-[0.68rem] font-semibold text-[#334155]/55 dark:text-muted-foreground">
            Page {pageNumber}
          </span>
        ) : null}
        {status === "loading" ? (
          <Loader2 className="size-4 animate-spin text-[#334155]/40" />
        ) : null}
        <canvas
          ref={canvasRef}
          aria-label={`${title} PDF thumbnail page ${pageNumber}`}
          className={status === "ready" ? "block bg-white shadow-sm" : "hidden"}
        />
      </span>
      <span className="mt-1 block text-center font-semibold text-[#334155]/65 dark:text-muted-foreground">
        {pageNumber}
      </span>
    </button>
  )
}

function pdfProxyUrl(pdfUrl: string) {
  return `/api/papers/pdf?url=${encodeURIComponent(pdfUrl)}`
}

function buildSearchResults(pageTexts: PdfPageText[], query: string): PdfSearchResult[] {
  const normalizedQuery = query.trim().toLowerCase()
  if (normalizedQuery.length < MIN_SEARCH_LENGTH) {
    return []
  }
  const results: PdfSearchResult[] = []
  for (const page of pageTexts) {
    const normalizedText = page.text.toLowerCase()
    const matchIndex = normalizedText.indexOf(normalizedQuery)
    if (matchIndex < 0) {
      continue
    }
    results.push({
      id: `${page.pageNumber}:${matchIndex}`,
      pageNumber: page.pageNumber,
      matchIndex,
      snippet: buildSnippet(page.text, matchIndex, query.trim().length),
    })
  }
  return results
}

function buildSnippet(text: string, matchIndex: number, queryLength: number) {
  const start = Math.max(0, matchIndex - 42)
  const end = Math.min(text.length, matchIndex + queryLength + 58)
  const prefix = start > 0 ? "... " : ""
  const suffix = end < text.length ? " ..." : ""
  return `${prefix}${text.slice(start, end).replace(/\s+/g, " ").trim()}${suffix}`
}

function clampSearchIndex(value: number, resultCount: number) {
  if (!Number.isFinite(value) || resultCount <= 0) {
    return 0
  }
  return Math.min(Math.max(value, 0), resultCount - 1)
}

function clampPage(value: number, numPages: number) {
  if (!Number.isFinite(value)) {
    return 1
  }
  return Math.min(Math.max(value, 1), Math.max(numPages, 1))
}

function clampScale(value: number) {
  if (!Number.isFinite(value)) {
    return 1
  }
  return Math.min(Math.max(Number(value.toFixed(2)), MIN_SCALE), MAX_SCALE)
}
