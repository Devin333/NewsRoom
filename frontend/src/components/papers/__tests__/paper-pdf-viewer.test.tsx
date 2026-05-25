import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { PaperPdfViewer } from "@/components/papers/shared/paper-pdf-viewer"

const pdfjsMock = vi.hoisted(() => {
  const GlobalWorkerOptions = { workerSrc: "" }
  const renderCancel = vi.fn()
  const render = vi.fn(() => ({ promise: Promise.resolve(), cancel: renderCancel }))
  const page = {
    getViewport: vi.fn(({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale })),
    render
  }
  const pdf = {
    numPages: 3,
    getPage: vi.fn(async (pageNumber: number) => {
      void pageNumber
      return page
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
    loadingDestroy,
    page,
    pdf,
    render,
    renderCancel,
    resolveDocument: () => resolveDocument(pdf),
    rejectDocument: () => rejectDocument(new Error("pdf failed")),
    reset: () => {
      GlobalWorkerOptions.workerSrc = ""
      renderCancel.mockReset()
      render.mockClear()
      page.getViewport.mockClear()
      pdf.getPage.mockReset()
      pdf.getPage.mockImplementation(async (pageNumber: number) => {
        void pageNumber
        return page
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

describe("PaperPdfViewer", () => {
  beforeEach(() => {
    pdfjsMock.reset()
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      setTransform: vi.fn()
    } as unknown as CanvasRenderingContext2D)
  })

  afterEach(() => {
    vi.restoreAllMocks()
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

    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

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
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

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
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

    const firstPage = await screen.findByRole("button", { name: "Go to page 1" })
    expect(firstPage).toHaveAttribute("aria-current", "page")

    fireEvent.click(screen.getByRole("button", { name: "Go to page 3" }))

    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Go to page 3" })).toHaveAttribute("aria-current", "page")
    expect(await screen.findByLabelText("Reader Paper PDF thumbnail page 3")).toBeInTheDocument()
  })

  it("keeps the main viewer usable when a thumbnail render fails", async () => {
    pdfjsMock.pdf.getPage.mockImplementation(async (pageNumber: number) => {
      if (pageNumber === 2) {
        throw new Error("thumbnail failed")
      }
      return pdfjsMock.page
    })

    renderViewer()
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Go to page 2" })).toHaveTextContent("Page 2")
  })

  it("supports keyboard page and zoom controls without crossing boundaries", async () => {
    renderViewer()
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

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
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

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
    await waitFor(() => expect(pdfjsMock.getDocument).toHaveBeenCalled())
    await act(async () => {
      pdfjsMock.resolveDocument()
    })

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
})
