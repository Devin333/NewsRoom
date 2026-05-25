import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { PaperPdfViewer } from "@/components/papers/shared/paper-pdf-viewer"

const pdfjsMock = vi.hoisted(() => {
  const GlobalWorkerOptions = { workerSrc: "" }
  const renderCancel = vi.fn()
  const thumbnailRenderStarts: number[] = []
  const thumbnailRenderCancels: number[] = []
  const pendingThumbnailRenders: Array<{ pageNumber: number; resolve: () => void }> = []
  let activeThumbnailRenderCount = 0
  let holdThumbnailRenders = false
  let maxActiveThumbnailRenderCount = 0
  const finishThumbnailRender = (done: { current: boolean }, resolve: () => void) => {
    if (done.current) {
      return
    }
    done.current = true
    activeThumbnailRenderCount = Math.max(0, activeThumbnailRenderCount - 1)
    resolve()
  }
  const render = vi.fn((pageNumber: number, params: { viewport: { width: number } }) => {
    const isThumbnail = params.viewport.width <= 120
    if (!isThumbnail) {
      return { promise: Promise.resolve(), cancel: renderCancel }
    }

    thumbnailRenderStarts.push(pageNumber)
    activeThumbnailRenderCount += 1
    maxActiveThumbnailRenderCount = Math.max(maxActiveThumbnailRenderCount, activeThumbnailRenderCount)
    const done = { current: false }
    let resolvePromise: () => void = () => undefined
    const promise = new Promise<void>((resolve) => {
      resolvePromise = resolve
    })
    const resolveThumbnail = () => finishThumbnailRender(done, resolvePromise)
    if (holdThumbnailRenders) {
      pendingThumbnailRenders.push({ pageNumber, resolve: resolveThumbnail })
    } else {
      queueMicrotask(resolveThumbnail)
    }
    const cancel = vi.fn(() => {
      renderCancel()
      thumbnailRenderCancels.push(pageNumber)
      resolveThumbnail()
    })
    return { promise, cancel }
  })
  const getViewport = vi.fn(({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }))
  const getTextContent = vi.fn(async (pageNumber: number) => ({
    items: (pageTexts.get(pageNumber) ?? "").split(/\s+/).filter(Boolean).map((str) => ({ str }))
  }))
  const defaultPageTexts = new Map([
    [1, "Diffusion model explains attention memory and document planning."],
    [2, "Latent Transformer benchmark improves retrieval and long context reading."],
    [3, "Engineering notes mention LATENT planning and benchmark limits."]
  ])
  const pageTexts = new Map(defaultPageTexts)
  let textContentFailure = false
  const createPage = (pageNumber: number) => ({
    getTextContent: vi.fn(async () => {
      if (textContentFailure) {
        throw new Error("text extraction failed")
      }
      return getTextContent(pageNumber)
    }),
    getViewport,
    render: vi.fn((params: { viewport: { width: number } }) => render(pageNumber, params))
  })
  const page = {
    getTextContent: vi.fn(async () => getTextContent(1)),
    getViewport,
    render: vi.fn((params: { viewport: { width: number } }) => render(1, params))
  }
  const pdf = {
    numPages: 3,
    getPage: vi.fn(async (pageNumber: number) => {
      return createPage(pageNumber)
    }),
    destroy: vi.fn(async () => undefined)
  }
  const getDocument = vi.fn()
  let resolveDocument: (value: typeof pdf) => void = () => undefined
  let rejectDocument: (reason: Error) => void = () => undefined
  const loadingDestroy = vi.fn()

  return {
    GlobalWorkerOptions,
    getDocument,
    getTextContent,
    loadingDestroy,
    page,
    pdf,
    pendingThumbnailRenders,
    render,
    renderCancel,
    thumbnailRenderCancels,
    thumbnailRenderStarts,
    resolveDocument: () => resolveDocument(pdf),
    rejectDocument: () => rejectDocument(new Error("pdf failed")),
    reset: () => {
      GlobalWorkerOptions.workerSrc = ""
      renderCancel.mockReset()
      render.mockClear()
      thumbnailRenderStarts.length = 0
      thumbnailRenderCancels.length = 0
      pendingThumbnailRenders.length = 0
      activeThumbnailRenderCount = 0
      holdThumbnailRenders = false
      maxActiveThumbnailRenderCount = 0
      getViewport.mockClear()
      getTextContent.mockClear()
      page.getTextContent.mockClear()
      page.getViewport.mockClear()
      pageTexts.clear()
      for (const [pageNumber, text] of defaultPageTexts.entries()) {
        pageTexts.set(pageNumber, text)
      }
      textContentFailure = false
      pdf.getPage.mockReset()
      pdf.getPage.mockImplementation(async (pageNumber: number) => {
        return createPage(pageNumber)
      })
      pdf.destroy.mockClear()
      loadingDestroy.mockReset()
      getDocument.mockReset()
      getDocument.mockImplementation(() => ({
        promise: new Promise<typeof pdf>((resolve, reject) => {
          resolveDocument = resolve
          rejectDocument = reject
        }),
        destroy: loadingDestroy
      }))
    },
    createPage,
    failTextContent: () => {
      textContentFailure = true
    },
    getMaxActiveThumbnailRenderCount: () => maxActiveThumbnailRenderCount,
    holdThumbnailRenders: () => {
      holdThumbnailRenders = true
    },
    releaseNextThumbnailRender: () => {
      pendingThumbnailRenders.shift()?.resolve()
    },
    setPageText: (pageNumber: number, text: string) => {
      pageTexts.set(pageNumber, text)
    }
  }
})

vi.mock("pdfjs-dist", () => ({
  default: {
    GlobalWorkerOptions: pdfjsMock.GlobalWorkerOptions,
    getDocument: pdfjsMock.getDocument
  },
  GlobalWorkerOptions: pdfjsMock.GlobalWorkerOptions,
  getDocument: pdfjsMock.getDocument
}))

function renderViewer(props: Partial<Parameters<typeof PaperPdfViewer>[0]> = {}) {
  return render(
    <PaperPdfViewer
      pdfUrl="https://arxiv.org/pdf/2605.00001.pdf"
      title="Reader Paper"
      locale="en"
      fallback={<div>Text fallback content</div>}
      {...props}
    />
  )
}

function installIntersectionObserverMock() {
  const previousIntersectionObserver = globalThis.IntersectionObserver
  const instances: MockIntersectionObserver[] = []

  class MockIntersectionObserver {
    readonly callback: IntersectionObserverCallback
    readonly options?: IntersectionObserverInit
    readonly targets = new Set<Element>()

    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
      this.callback = callback
      this.options = options
      instances.push(this)
    }

    disconnect = vi.fn(() => {
      this.targets.clear()
    })

    observe = vi.fn((target: Element) => {
      this.targets.add(target)
    })

    takeRecords = vi.fn(() => [])

    unobserve = vi.fn((target: Element) => {
      this.targets.delete(target)
    })
  }

  Object.defineProperty(globalThis, "IntersectionObserver", {
    configurable: true,
    value: MockIntersectionObserver,
    writable: true
  })

  return {
    getInstances: () => instances,
    restore: () => {
      if (previousIntersectionObserver) {
        Object.defineProperty(globalThis, "IntersectionObserver", {
          configurable: true,
          value: previousIntersectionObserver,
          writable: true
        })
      } else {
        Reflect.deleteProperty(globalThis, "IntersectionObserver")
      }
    },
    trigger: (target: Element, isIntersecting: boolean) => {
      for (const instance of instances) {
        if (!instance.targets.has(target)) {
          continue
        }
        instance.callback(
          [
            {
              isIntersecting,
              target
            } as IntersectionObserverEntry
          ],
          instance as unknown as IntersectionObserver
        )
      }
    }
  }
}

async function resolveViewerDocument() {
  await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
  await act(async () => {
    pdfjsMock.resolveDocument()
  })
  expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument()
}

describe("PaperPdfViewer", () => {
  beforeEach(() => {
    pdfjsMock.reset()
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      setTransform: vi.fn()
    } as unknown as CanvasRenderingContext2D)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(globalThis, "IntersectionObserver")
  })

  it("shows loading state and loads only through the PDF proxy", async () => {
    renderViewer()

    expect(screen.getAllByText("Loading PDF")).toHaveLength(2)
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    expect(pdfjsMock.GlobalWorkerOptions.workerSrc).toBe("/pdf.worker.min.mjs")
    expect(pdfjsMock.getDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        url: "/api/papers/pdf?url=https%3A%2F%2Farxiv.org%2Fpdf%2F2605.00001.pdf"
      })
    )
    expect(pdfjsMock.getDocument).not.toHaveBeenCalledWith(
      expect.objectContaining({ url: "https://arxiv.org/pdf/2605.00001.pdf" })
    )
  })

  it("renders page count when the document resolves", async () => {
    renderViewer()

    await resolveViewerDocument()

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument()
    expect(screen.getByText("/ 3")).toBeInTheDocument()
    await waitFor(() => expect(pdfjsMock.pdf.getPage).toHaveBeenCalledWith(1))
  })

  it("restores and clamps the initial page", async () => {
    const onPageChange = vi.fn()
    const { rerender } = renderViewer({ initialPage: 2, onPageChange })

    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument()
    await waitFor(() => expect(onPageChange).toHaveBeenCalledWith(2, 3))

    pdfjsMock.reset()
    rerender(
      <PaperPdfViewer
        pdfUrl="https://arxiv.org/pdf/2605.00001.pdf?reload=1"
        title="Reader Paper"
        locale="en"
        fallback={<div>Text fallback content</div>}
        initialPage={99}
      />
    )

    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()
  })

  it("navigates pages and disables controls at boundaries", async () => {
    renderViewer()
    await resolveViewerDocument()

    const previous = await screen.findByRole("button", { name: "Previous page" })
    const next = screen.getByRole("button", { name: "Next page" })
    expect(previous).toBeDisabled()

    fireEvent.click(next)
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument()
    fireEvent.click(next)
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()
    expect(next).toBeDisabled()
  })

  it("renders thumbnails and navigates by selected thumbnail", async () => {
    renderViewer()
    await resolveViewerDocument()

    const firstPage = await screen.findByRole("button", { name: "Go to page 1" })
    expect(firstPage).toHaveAttribute("aria-current", "page")

    fireEvent.click(screen.getByRole("button", { name: "Go to page 3" }))

    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Go to page 3" })).toHaveAttribute("aria-current", "page")
    expect(await screen.findByLabelText("Reader Paper PDF thumbnail page 3")).toBeInTheDocument()
  })

  it("lazily renders thumbnails when they enter the observer margin", async () => {
    const intersection = installIntersectionObserverMock()
    renderViewer()
    await resolveViewerDocument()

    await waitFor(() => expect(intersection.getInstances()).toHaveLength(3))
    expect(intersection.getInstances()[0]?.options?.rootMargin).toBe("240px")
    expect(pdfjsMock.thumbnailRenderStarts).toEqual([])

    const firstPage = screen.getByRole("button", { name: "Go to page 1" })
    act(() => {
      intersection.trigger(firstPage, true)
    })

    await waitFor(() => expect(pdfjsMock.thumbnailRenderStarts).toContain(1))
    expect(await screen.findByLabelText("Reader Paper PDF thumbnail page 1")).toBeInTheDocument()
    intersection.restore()
  })

  it("limits concurrent thumbnail renders to two jobs", async () => {
    const intersection = installIntersectionObserverMock()
    pdfjsMock.holdThumbnailRenders()
    renderViewer()
    await resolveViewerDocument()
    await waitFor(() => expect(intersection.getInstances()).toHaveLength(3))

    for (const button of screen.getAllByRole("button", { name: /Go to page/ })) {
      act(() => {
        intersection.trigger(button, true)
      })
    }

    await waitFor(() => expect(pdfjsMock.thumbnailRenderStarts).toEqual([1, 2]))
    expect(pdfjsMock.getMaxActiveThumbnailRenderCount()).toBe(2)

    act(() => {
      pdfjsMock.releaseNextThumbnailRender()
    })

    await waitFor(() => expect(pdfjsMock.thumbnailRenderStarts).toEqual([1, 2, 3]))
    expect(pdfjsMock.getMaxActiveThumbnailRenderCount()).toBe(2)
    intersection.restore()
  })

  it("cancels active and pending thumbnail renders when thumbnails leave view", async () => {
    const intersection = installIntersectionObserverMock()
    pdfjsMock.holdThumbnailRenders()
    renderViewer()
    await resolveViewerDocument()
    await waitFor(() => expect(intersection.getInstances()).toHaveLength(3))

    const buttons = screen.getAllByRole("button", { name: /Go to page/ })
    for (const button of buttons) {
      act(() => {
        intersection.trigger(button, true)
      })
    }
    await waitFor(() => expect(pdfjsMock.thumbnailRenderStarts).toEqual([1, 2]))

    act(() => {
      intersection.trigger(buttons[0]!, false)
      intersection.trigger(buttons[2]!, false)
      pdfjsMock.releaseNextThumbnailRender()
      pdfjsMock.releaseNextThumbnailRender()
    })

    await waitFor(() => expect(pdfjsMock.thumbnailRenderCancels).toContain(1))
    expect(pdfjsMock.thumbnailRenderStarts).not.toContain(3)
    intersection.restore()
  })

  it("keeps the main viewer usable when a thumbnail render fails", async () => {
    pdfjsMock.pdf.getPage.mockImplementation(async (pageNumber: number) => {
      if (pageNumber === 2) {
        throw new Error("thumbnail failed")
      }
      return pdfjsMock.createPage(pageNumber)
    })

    renderViewer()
    await resolveViewerDocument()

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Go to page 2" })).toHaveTextContent("Page 2")
  })

  it("supports keyboard page and zoom controls without crossing boundaries", async () => {
    renderViewer()
    await resolveViewerDocument()

    const viewer = await screen.findByLabelText("Reader Paper PDF viewer")
    fireEvent.keyDown(viewer, { key: "ArrowRight" })
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument()

    fireEvent.keyDown(viewer, { key: "PageDown" })
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()

    fireEvent.keyDown(viewer, { key: "ArrowRight" })
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument()

    fireEvent.keyDown(viewer, { key: "+" })
    expect(await screen.findByText("125%")).toBeInTheDocument()

    fireEvent.keyDown(viewer, { key: "-" })
    fireEvent.keyDown(viewer, { key: "-" })
    expect(await screen.findByText("75%")).toBeInTheDocument()
  })

  it("clamps jump page input", async () => {
    renderViewer()
    await resolveViewerDocument()

    const input = await screen.findByLabelText("Page number")
    fireEvent.change(input, { target: { value: "99" } })
    fireEvent.submit(input.closest("form")!)
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()

    fireEvent.change(input, { target: { value: "-20" } })
    fireEvent.submit(input.closest("form")!)
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument()
  })

  it("clamps zoom controls", async () => {
    renderViewer()
    await resolveViewerDocument()

    const zoomIn = await screen.findByRole("button", { name: "Zoom in" })
    const zoomOut = screen.getByRole("button", { name: "Zoom out" })
    fireEvent.click(zoomIn)
    fireEvent.click(zoomIn)
    fireEvent.click(zoomIn)
    fireEvent.click(zoomIn)
    fireEvent.click(zoomIn)
    expect(await screen.findByText("200%")).toBeInTheDocument()
    expect(zoomIn).toBeDisabled()

    fireEvent.click(zoomOut)
    fireEvent.click(zoomOut)
    fireEvent.click(zoomOut)
    fireEvent.click(zoomOut)
    fireEvent.click(zoomOut)
    fireEvent.click(zoomOut)
    expect(await screen.findByText("75%")).toBeInTheDocument()
    expect(zoomOut).toBeDisabled()
  })

  it("renders fallback when PDF loading fails", async () => {
    renderViewer()

    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.rejectDocument()
    })

    expect(await screen.findByText("PDF could not be rendered; showing text fallback.")).toBeInTheDocument()
    expect(screen.getByText("Text fallback content")).toBeInTheDocument()
  })

  it("searches extracted text across pages with case-insensitive matches", async () => {
    renderViewer()
    await resolveViewerDocument()

    await waitFor(() => expect(pdfjsMock.getTextContent).toHaveBeenCalledWith(3))
    fireEvent.change(screen.getByLabelText("Search PDF text"), { target: { value: "LATENT" } })

    expect(await screen.findByText("2 results")).toBeInTheDocument()
    expect(screen.getByText(/Latent Transformer benchmark improves retrieval/i)).toBeInTheDocument()
    expect(screen.getByText(/Engineering notes mention LATENT planning/i)).toBeInTheDocument()
  })

  it("hides search results for short queries", async () => {
    renderViewer()
    await resolveViewerDocument()

    await waitFor(() => expect(pdfjsMock.getTextContent).toHaveBeenCalledWith(3))
    fireEvent.change(screen.getByLabelText("Search PDF text"), { target: { value: "l" } })

    expect(await screen.findByText("Enter at least 2 characters.")).toBeInTheDocument()
    expect(screen.queryByText(/Latent Transformer benchmark improves retrieval/i)).not.toBeInTheDocument()
  })

  it("navigates to clicked search results and reports page progress", async () => {
    const onPageChange = vi.fn()
    renderViewer({ onPageChange })
    await resolveViewerDocument()

    await waitFor(() => expect(pdfjsMock.getTextContent).toHaveBeenCalledWith(3))
    fireEvent.change(screen.getByLabelText("Search PDF text"), { target: { value: "latent" } })

    const thirdPageResult = await screen.findByText(/Engineering notes mention LATENT planning/i)
    fireEvent.click(thirdPageResult.closest("button")!)

    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()
    await waitFor(() => expect(onPageChange).toHaveBeenCalledWith(3, 3))
  })

  it("clamps previous and next search result navigation", async () => {
    renderViewer()
    await resolveViewerDocument()

    await waitFor(() => expect(pdfjsMock.getTextContent).toHaveBeenCalledWith(3))
    fireEvent.change(screen.getByLabelText("Search PDF text"), { target: { value: "latent" } })

    expect(await screen.findByText("2 results")).toBeInTheDocument()
    const previous = screen.getByRole("button", { name: "Previous search result" })
    const next = screen.getByRole("button", { name: "Next search result" })
    expect(previous).toBeDisabled()

    fireEvent.click(next)
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()
    expect(next).toBeDisabled()

    fireEvent.click(previous)
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument()
    expect(previous).toBeDisabled()
  })

  it("keeps the PDF canvas readable when text extraction fails", async () => {
    pdfjsMock.failTextContent()
    renderViewer()
    await resolveViewerDocument()

    expect(await screen.findByText("PDF search text is unavailable.")).toBeInTheDocument()
    expect(screen.getByLabelText("Reader Paper PDF page 1")).toBeInTheDocument()
    expect(screen.queryByText("Text fallback content")).not.toBeInTheDocument()
  })
})
