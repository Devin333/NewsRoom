"use client"

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"
import { ChevronLeft, ChevronRight, FileWarning, Loader2, ZoomIn, ZoomOut } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { Locale } from "@/lib/papers/types"

type PaperPdfViewerProps = {
  pdfUrl: string
  title: string
  locale: Locale
  fallback: ReactNode
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

const MIN_SCALE = 0.75
const MAX_SCALE = 2
const SCALE_STEP = 0.25

export function PaperPdfViewer({ pdfUrl, title, locale, fallback, onPageChange }: PaperPdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const renderTaskRef = useRef<PdfRenderTask | null>(null)
  const [pdfDocument, setPdfDocument] = useState<PdfDocument | null>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const [isRendering, setIsRendering] = useState(false)
  const [pageNumber, setPageNumber] = useState(1)
  const [pageInput, setPageInput] = useState("1")
  const [numPages, setNumPages] = useState(0)
  const [scale, setScale] = useState(1)

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
          withCredentials: false
        }) as unknown as PdfLoadingTask
        const pdf = await loadingTask.promise
        loadedDocument = pdf
        if (cancelled) {
          await pdf.destroy()
          return
        }
        setPdfDocument(pdf)
        setNumPages(pdf.numPages)
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

  if (status === "error") {
    return (
      <div className="min-h-[42rem]">
        <div className="border-b border-[#d8dfd8] bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-border dark:bg-amber-950/30 dark:text-amber-100">
          <div className="flex items-center gap-2 font-semibold">
            <FileWarning className="size-4" />
            {locale === "zh" ? "PDF 暂不可渲染，已切换到文本阅读。" : "PDF could not be rendered; showing text fallback."}
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

  function goToPage(nextPage: number) {
    const clamped = clampPage(nextPage, numPages)
    setPageNumber(clamped)
    setPageInput(String(clamped))
  }

  function handlePageSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    goToPage(Number.parseInt(pageInput, 10))
  }

  function changeScale(nextScale: number) {
    setScale(clampScale(nextScale))
  }

  return (
    <div className="flex min-h-[42rem] flex-col bg-[#f8faf9] dark:bg-background">
      <div className="flex flex-col gap-3 border-b border-[#d8dfd8] bg-white px-4 py-3 dark:border-border dark:bg-card lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-[#334155] dark:text-foreground">{title}</h2>
          <p className="mt-1 text-xs text-[#334155]/55 dark:text-muted-foreground">
            {status === "ready" ? `Page ${pageNumber} of ${numPages}` : locale === "zh" ? "正在加载 PDF" : "Loading PDF"}
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

      <div className="relative flex h-[78vh] min-h-[38rem] flex-1 justify-center overflow-auto bg-[#eef4ef] p-4 dark:bg-secondary/30">
        {status === "loading" ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-background/80">
            <div className="inline-flex items-center gap-2 rounded-md border border-[#d8dfd8] bg-white px-4 py-3 text-sm font-semibold text-[#334155]/70 shadow-sm dark:border-border dark:bg-card dark:text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              {locale === "zh" ? "正在加载 PDF" : "Loading PDF"}
            </div>
          </div>
        ) : null}
        {isRendering && status === "ready" ? (
          <div className="absolute right-4 top-4 inline-flex items-center gap-2 rounded-md bg-white px-3 py-2 text-xs font-semibold text-[#334155]/65 shadow-sm dark:bg-card dark:text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {locale === "zh" ? "渲染中" : "Rendering"}
          </div>
        ) : null}
        <canvas
          ref={canvasRef}
          aria-label={`${title} PDF page ${pageNumber}`}
          className="block self-start bg-white shadow-lg"
        />
      </div>
    </div>
  )
}

function pdfProxyUrl(pdfUrl: string) {
  return `/api/papers/pdf?url=${encodeURIComponent(pdfUrl)}`
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
