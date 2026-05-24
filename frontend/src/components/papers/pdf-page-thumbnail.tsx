"use client"

import { useEffect, useRef, useState } from "react"

type PdfPageThumbnailProps = {
  className?: string
  pdfUrl: string
  title: string
}

export function PdfPageThumbnail({ className, pdfUrl, title }: PdfPageThumbnailProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [failed, setFailed] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    let cleanup: (() => void) | undefined

    async function renderPdfPage() {
      setFailed(false)
      setReady(false)
      try {
        const pdfjs = await import("pdfjs-dist")
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs"

        const proxyUrl = `/api/papers/pdf?url=${encodeURIComponent(pdfUrl)}`
        const loadingTask = pdfjs.getDocument({
          url: proxyUrl,
          withCredentials: false
        })
        cleanup = () => loadingTask.destroy()

        const pdf = await loadingTask.promise
        const page = await pdf.getPage(1)
        const viewport = page.getViewport({ scale: 1 })
        const targetWidth = 360
        const scale = targetWidth / viewport.width
        const scaledViewport = page.getViewport({ scale })
        const canvas = canvasRef.current
        const context = canvas?.getContext("2d")

        if (!canvas || !context || cancelled) {
          await pdf.destroy()
          return
        }

        canvas.width = Math.floor(scaledViewport.width)
        canvas.height = Math.floor(scaledViewport.height)
        canvas.style.width = "100%"
        canvas.style.height = "100%"

        const renderTask = page.render({
          canvasContext: context,
          viewport: scaledViewport
        })
        cleanup = () => {
          renderTask.cancel()
          void pdf.destroy()
        }
        await renderTask.promise

        if (!cancelled) {
          setReady(true)
          void pdf.destroy()
        }
      } catch {
        if (!cancelled) {
          setFailed(true)
        }
      }
    }

    void renderPdfPage()

    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [pdfUrl])

  if (failed) {
    return (
      <div className={className}>
        <div className="flex h-full w-full items-center justify-center bg-white px-4 text-center text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-400">
          PDF preview unavailable
        </div>
      </div>
    )
  }

  return (
    <div className={className}>
      {!ready ? (
        <div className="flex h-full w-full items-center justify-center bg-white text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-slate-300">
          Rendering PDF
        </div>
      ) : null}
      <canvas
        ref={canvasRef}
        aria-label={`${title} PDF first page`}
        className={ready ? "h-full w-full bg-white object-contain" : "hidden"}
      />
    </div>
  )
}
