"use client"

import Link from "next/link"
import { GitFork } from "lucide-react"
import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react"
import { formatPaperDate, paperTitle } from "@/lib/papers/format"
import type { Locale } from "@/lib/papers/types"
import type { DrawerState, NotePopoverState, OpenReaderPageProps, ReaderParagraph, ReaderSelection, ReaderSettings, SelectionMenuState } from "./open-reader-types"
import { buildReaderParagraphs, buildReaderToc, clamp, getSelectionOffsetsWithinElement, getSelectionStatus, makeMaterialSummary, mockExample, mockExplain, safeJsonParse, storageKey } from "./open-reader-utils"
import { useOpenReaderSelections, useOpenReaderSettings } from "./open-reader-state"
import styles from "./open-reader.module.css"

export function OpenReaderPage({ reader, locale, backHref = "/papers" }: OpenReaderPageProps) {
  const paper = reader.paper
  const title = paperTitle(paper, locale)
  const paragraphs = useMemo(() => buildReaderParagraphs(reader, locale), [reader, locale])
  const toc = useMemo(() => buildReaderToc(paragraphs), [paragraphs])
  const { settings, patchSettings } = useOpenReaderSettings(paper.id)
  const { selections, events, createTempSelection, discardAllTemp, updateNote, confirmExplain, confirmExample, toggleConfused } = useOpenReaderSelections(paper.id)
  const materials = useMemo(() => makeMaterialSummary(paper.id, selections, events), [paper.id, selections, events])

  const contentRef = useRef<HTMLElement | null>(null)
  const paragraphRefs = useRef(new Map<string, HTMLParagraphElement>())
  const sectionRefs = useRef(new Map<string, HTMLElement>())

  const [activeSectionId, setActiveSectionId] = useState<string | null>(toc[0]?.id ?? null)
  const [menu, setMenu] = useState<SelectionMenuState | null>(null)
  const [note, setNote] = useState<NotePopoverState | null>(null)
  const [drawer, setDrawer] = useState<DrawerState | null>(null)

  const menuSelection = menu ? selections.find((item) => item.id === menu.selectionId) : undefined
  const noteSelection = note ? selections.find((item) => item.id === note.selectionId) : undefined
  const drawerSelection = drawer?.selectionId ? selections.find((item) => item.id === drawer.selectionId) : undefined

  useEffect(() => {
    function onClick(event: MouseEvent) {
      const target = event.target as HTMLElement | null
      if (!target) return
      if (target.closest("[data-open-reader-keep-open]")) return
      setMenu(null)
      setNote(null)
      if (drawer) setDrawer(null)
      discardAllTemp()
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return
      setMenu(null)
      setNote(null)
      setDrawer(null)
      discardAllTemp()
    }

    document.addEventListener("click", onClick)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("click", onClick)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [discardAllTemp, drawer])

  useEffect(() => {
    function onScroll() {
      let active = toc[0]?.id ?? null
      for (const item of toc) {
        const node = sectionRefs.current.get(item.id)
        if (node && node.getBoundingClientRect().top < 120) active = item.id
      }
      setActiveSectionId(active)
      const max = document.documentElement.scrollHeight - window.innerHeight
      const progress = max > 0 ? Math.min(100, Math.max(14, (window.scrollY / max) * 100)) : 14
      document.documentElement.style.setProperty("--open-reader-progress", `${progress}%`)
    }
    window.addEventListener("scroll", onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener("scroll", onScroll)
  }, [toc])

  function bindParagraph(id: string) {
    return (node: HTMLParagraphElement | null) => {
      if (node) paragraphRefs.current.set(id, node)
      else paragraphRefs.current.delete(id)
    }
  }

  function bindSection(id: string) {
    return (node: HTMLElement | null) => {
      if (node) sectionRefs.current.set(id, node)
      else sectionRefs.current.delete(id)
    }
  }

  function handleMouseUp() {
    window.setTimeout(() => {
      const selection = window.getSelection()
      if (!selection || selection.isCollapsed || !selection.rangeCount) return
      const range = selection.getRangeAt(0)
      const paragraphEl = closestParagraph(range.commonAncestorContainer)
      if (!paragraphEl || !contentRef.current?.contains(paragraphEl)) return
      const paragraphId = paragraphEl.dataset.paragraphId
      const paragraph = paragraphs.find((item) => item.id === paragraphId)
      if (!paragraph) return
      const offsets = getSelectionOffsetsWithinElement(paragraphEl, range)
      if (!offsets) return
      const selectedText = paragraph.text.slice(offsets.startOffset, offsets.endOffset).trim()
      if (selectedText.length < 2) return

      discardAllTemp()
      const selectionId = createTempSelection({ paragraph, selectedText, startOffset: offsets.startOffset, endOffset: offsets.endOffset })
      const rect = range.getBoundingClientRect()
      setMenu({ selectionId, x: rect.left, y: rect.bottom + 8 })
      selection.removeAllRanges()
    }, 0)
  }

  function closestParagraph(node: Node) {
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node as HTMLElement
    return element?.closest?.("[data-paragraph-id]") as HTMLParagraphElement | null
  }

  function openSelectionMenu(selection: ReaderSelection, rect: DOMRect) {
    setMenu({ selectionId: selection.id, x: rect.left, y: rect.bottom + 8 })
  }

  function openMaterials() {
    setMenu(null)
    setNote(null)
    setDrawer({ mode: "materials" })
  }

  const themeClass = settings.theme === "dark" ? styles.darkTheme : settings.theme === "light" ? styles.lightTheme : styles.warmTheme

  return (
    <main
      className={`${styles.openReader} ${themeClass}`}
      style={{ ["--reader-font-size" as string]: `${settings.fontSize}px`, ["--reader-content-width" as string]: `${settings.contentWidth}px` }}
    >
      <header className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <Link className={styles.readerMarkLink} href={backHref} aria-label="返回论文列表">
            <GitFork aria-hidden="true" className={styles.readerMarkIcon} />
          </Link>
          <span className={styles.topTitle}>{title}</span>
        </div>
        <div className={styles.progressTrack}><span /></div>
      </header>

      <ReaderSettingsDock settings={settings} onChange={patchSettings} />

      <article className={styles.readerLayout}>
        <section className={styles.titleBlock}>
          <div className={styles.kicker}>Open Reader</div>
          <h1>{title}</h1>
          <p>{paper.authors?.join(", ")} · {paper.venue ?? "Paper"} · {formatPaperDate(paper.publishedAt, locale)}</p>
        </section>

        <section ref={contentRef} className={styles.paperCard} onMouseUp={handleMouseUp}>
          {toc.map((section) => {
            const sectionParagraphs = paragraphs.filter((paragraph) => paragraph.sectionId === section.id)
            return (
              <section key={section.id} ref={bindSection(section.id)} className={styles.readerSection}>
                <div className={styles.sectionLabel}>{section.sectionType}</div>
                <h2>{section.title}</h2>
                {sectionParagraphs.map((paragraph) => (
                  <ReaderParagraphView
                    key={paragraph.id}
                    paragraph={paragraph}
                    paragraphRef={bindParagraph(paragraph.id)}
                    selections={selections.filter((item) => item.paragraphId === paragraph.id)}
                    onOpenSelectionMenu={openSelectionMenu}
                  />
                ))}
              </section>
            )
          })}
        </section>
      </article>

      <FloatingToc paperId={paper.id} items={toc} activeSectionId={activeSectionId} materialCount={materials.selections.length} onNavigate={(id) => sectionRefs.current.get(id)?.scrollIntoView({ behavior: "smooth", block: "start" })} onOpenMaterials={openMaterials} />

      {menu && menuSelection ? (
        <SelectionActionMenu
          selection={menuSelection}
          x={menu.x}
          y={menu.y}
          onNote={() => { setMenu(null); setNote({ selectionId: menuSelection.id, x: menu.x, y: menu.y }) }}
          onExplain={() => { setMenu(null); setDrawer({ mode: "explain", selectionId: menuSelection.id }) }}
          onExample={() => { setMenu(null); setDrawer({ mode: "example", selectionId: menuSelection.id }) }}
          onToggleConfused={() => { toggleConfused(menuSelection.id); setMenu(null) }}
        />
      ) : null}

      {note && noteSelection ? (
        <ReaderNotePopover selection={noteSelection} x={note.x} y={note.y} onChange={(value) => updateNote(noteSelection.id, value)} />
      ) : null}

      {drawer ? (
        <ReaderAssistDrawer
          drawer={drawer}
          selection={drawerSelection}
          materialSummary={materials}
          locale={locale}
          drawerWidth={settings.drawerWidth}
          onWidthChange={(drawerWidth) => patchSettings({ drawerWidth })}
          onClose={() => { setDrawer(null); discardAllTemp() }}
          onConfirmExplain={(selectionId, question) => confirmExplain(selectionId, question)}
          onConfirmExample={(selectionId, question) => confirmExample(selectionId, question)}
        />
      ) : null}
    </main>
  )
}

function ReaderParagraphView({ paragraph, selections, paragraphRef, onOpenSelectionMenu }: {
  paragraph: ReaderParagraph
  selections: ReaderSelection[]
  paragraphRef: (node: HTMLParagraphElement | null) => void
  onOpenSelectionMenu: (selection: ReaderSelection, rect: DOMRect) => void
}) {
  const segments = buildSegments(paragraph.text, selections)
  return (
    <p ref={paragraphRef} className={styles.paragraph} data-paragraph-id={paragraph.id}>
      {segments.map((segment, index) => segment.selection ? (
        <mark
          key={segment.selection.id}
          data-selection-id={segment.selection.id}
          className={`${styles.selectionMark} ${styles[`selection_${getSelectionStatus(segment.selection)}`]}`}
          onClick={(event) => { event.stopPropagation(); onOpenSelectionMenu(segment.selection!, event.currentTarget.getBoundingClientRect()) }}
          onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); onOpenSelectionMenu(segment.selection!, event.currentTarget.getBoundingClientRect()) }}
        >
          {segment.text}
        </mark>
      ) : <span key={index}>{segment.text}</span>)}
    </p>
  )
}

function buildSegments(text: string, selections: ReaderSelection[]) {
  const sorted = selections
    .filter((selection) => selection.startOffset >= 0 && selection.endOffset <= text.length && selection.startOffset < selection.endOffset)
    .sort((a, b) => a.startOffset - b.startOffset)
  const segments: { text: string; selection?: ReaderSelection }[] = []
  let cursor = 0
  for (const selection of sorted) {
    if (selection.startOffset < cursor) continue
    if (selection.startOffset > cursor) segments.push({ text: text.slice(cursor, selection.startOffset) })
    segments.push({ text: text.slice(selection.startOffset, selection.endOffset), selection })
    cursor = selection.endOffset
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) })
  return segments.length ? segments : [{ text }]
}

function ReaderSettingsDock({ settings, onChange }: { settings: ReaderSettings; onChange: (patch: Partial<ReaderSettings>) => void }) {
  return (
    <aside className={styles.settingsDock} data-open-reader-keep-open>
      <button type="button" className={styles.settingsOrb} aria-label="阅读设置">Aa</button>
      <div className={styles.settingsPanel}>
        <div className={styles.settingsTitle}>阅读设置</div>
        <div className={styles.settingRow}><label>字体大小</label><input type="range" min={12} max={38} value={settings.fontSize} onChange={(event) => onChange({ fontSize: Number(event.target.value) })} /></div>
        <div className={styles.settingRow}><label>文本宽度</label><input type="range" min={520} max={2000} value={settings.contentWidth} onChange={(event) => onChange({ contentWidth: Number(event.target.value) })} /></div>
        <div className={styles.themeRow}>{(["light", "warm", "dark"] as const).map((theme) => <button key={theme} type="button" className={`${styles.themeButton} ${settings.theme === theme ? styles.activeTheme : ""}`} onClick={() => onChange({ theme })}>{theme === "light" ? "浅色" : theme === "warm" ? "暖色" : "深色"}</button>)}</div>
      </div>
    </aside>
  )
}

function FloatingToc({ paperId, items, activeSectionId, materialCount, onNavigate, onOpenMaterials }: { paperId: string; items: { id: string; title: string; paragraphCount: number }[]; activeSectionId: string | null; materialCount: number; onNavigate: (id: string) => void; onOpenMaterials: () => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [side, setSide] = useState<"left" | "right">("left")
  const [dragging, setDragging] = useState(false)
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const offsetRef = useRef({ x: 0, y: 0 })
  const positionRef = useRef<{ x: number; y: number } | null>(null)
  const positionKey = useMemo(() => storageKey(paperId, "toc-position"), [paperId])

  useEffect(() => {
    if (typeof window === "undefined") return
    const saved = safeJsonParse<{ x: number; y: number } | null>(window.localStorage.getItem(positionKey), null)
    if (!saved || !Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return
    const next = {
      x: clamp(saved.x, 8, window.innerWidth - 62),
      y: clamp(saved.y, 58, window.innerHeight - 66),
    }
    positionRef.current = next
    setPosition(next)
    setSide(next.x + 31 > window.innerWidth / 2 ? "right" : "left")
  }, [positionKey])

  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragging) return
      const x = Math.max(8, Math.min(window.innerWidth - 62, event.clientX - offsetRef.current.x))
      const y = Math.max(58, Math.min(window.innerHeight - 66, event.clientY - offsetRef.current.y))
      const next = { x, y }
      positionRef.current = next
      setPosition(next)
      setSide(x + 31 > window.innerWidth / 2 ? "right" : "left")
    }
    function onUp() {
      setDragging(false)
      if (positionRef.current) {
        window.localStorage.setItem(positionKey, JSON.stringify(positionRef.current))
      }
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
  }, [dragging, positionKey])

  return (
    <div ref={rootRef} className={`${styles.floatingToc} ${side === "right" ? styles.sideRight : styles.sideLeft}`} style={position ? { left: position.x, top: position.y, bottom: "auto" } : undefined} data-open-reader-keep-open>
      <button type="button" className={styles.tocOrb} onMouseDown={(event) => { const rect = rootRef.current?.getBoundingClientRect(); if (rect) { offsetRef.current = { x: event.clientX - rect.left, y: event.clientY - rect.top }; setDragging(true); event.preventDefault() } }}>目</button>
      <nav className={styles.tocPanel}>
        <div className={styles.tocPanelTitle}>悬浮目录 · 可拖动</div>
        {items.map((item) => <button key={item.id} type="button" className={`${styles.tocLink} ${activeSectionId === item.id ? styles.activeTocLink : ""}`} onClick={() => onNavigate(item.id)}><span>{item.title}</span><small>{item.paragraphCount} 段</small></button>)}
        <button type="button" className={styles.tocLink} onClick={onOpenMaterials}><span>阅读素材</span><small>{materialCount}</small></button>
      </nav>
    </div>
  )
}

function SelectionActionMenu({ selection, x, y, onNote, onExplain, onExample, onToggleConfused }: { selection: ReaderSelection; x: number; y: number; onNote: () => void; onExplain: () => void; onExample: () => void; onToggleConfused: () => void }) {
  return (
    <div className={styles.selectionMenu} style={floatingLayerStyle(x, y, 230, 190, 10)} data-open-reader-keep-open>
      <button type="button" className={styles.menuItem} onClick={onNote}>笔记</button>
      <button type="button" className={styles.menuItem} onClick={onExplain}>解释选中内容</button>
      <button type="button" className={styles.menuItem} onClick={onExample}>举例说明</button>
      <button type="button" className={`${styles.menuItem} ${selection.confused ? styles.dangerMenuItem : ""}`} onClick={onToggleConfused}>{selection.confused ? "取消标记为不懂" : "标记为不懂"}</button>
    </div>
  )
}

function ReaderNotePopover({ selection, x, y, onChange }: { selection: ReaderSelection; x: number; y: number; onChange: (value: string) => void }) {
  const [value, setValue] = useState(selection.noteText)
  useEffect(() => { setValue(selection.noteText) }, [selection.id, selection.noteText])
  useEffect(() => {
    if (value === selection.noteText) return
    const timer = window.setTimeout(() => onChange(value), 360)
    return () => window.clearTimeout(timer)
  }, [onChange, selection.noteText, value])
  return (
    <div className={styles.notePopover} style={floatingLayerStyle(x, y, 410, 250, 14)} data-open-reader-keep-open>
      <div className={styles.noteHead}><strong>笔记</strong><span>{selection.sectionTitle}</span></div>
      <div className={styles.selectedPreview}>{selection.selectedText}</div>
      <textarea autoFocus value={value} placeholder="写下你的理解、疑问或复现想法。输入后自动保存。" onChange={(event) => setValue(event.target.value)} />
    </div>
  )
}

function ReaderAssistDrawer({ drawer, selection, materialSummary, locale, drawerWidth, onWidthChange, onClose, onConfirmExplain, onConfirmExample }: { drawer: DrawerState; selection?: ReaderSelection; materialSummary: ReturnType<typeof makeMaterialSummary>; locale: Locale; drawerWidth: number; onWidthChange: (width: number) => void; onClose: () => void; onConfirmExplain: (id: string, question: string) => void; onConfirmExample: (id: string, question: string) => void }) {
  const [question, setQuestion] = useState("")
  const [generated, setGenerated] = useState("")
  const resizingRef = useRef(false)
  useEffect(() => { setQuestion(""); setGenerated("") }, [drawer.mode, drawer.selectionId])
  useEffect(() => {
    function onMove(event: MouseEvent) { if (!resizingRef.current) return; onWidthChange(Math.max(360, Math.min(Math.min(window.innerWidth - 80, 920), window.innerWidth - event.clientX - 22))) }
    function onUp() { resizingRef.current = false; document.body.classList.remove(styles.drawerResizingBody) }
    window.addEventListener("mousemove", onMove); window.addEventListener("mouseup", onUp)
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
  }, [onWidthChange])
  const title = drawer.mode === "materials" ? "阅读素材汇总" : drawer.mode === "example" ? "举例说明" : "解释选中内容"
  function confirm(useDefault: boolean) {
    if (!selection) return
    const q = useDefault ? "" : question.trim()
    if (drawer.mode === "explain") { onConfirmExplain(selection.id, q); setGenerated(mockExplain(selection, q, locale)) }
    if (drawer.mode === "example") { onConfirmExample(selection.id, q); setGenerated(mockExample(selection, q, locale)) }
  }
  return (
    <aside className={styles.assistDrawer} style={{ width: `min(${drawerWidth}px, calc(100vw - 44px))` }} data-open-reader-keep-open>
      <div className={styles.drawerResizeHandle} onMouseDown={(event) => { resizingRef.current = true; document.body.classList.add(styles.drawerResizingBody); event.preventDefault(); event.stopPropagation() }} />
      <div className={styles.drawerHead}><strong>{title}</strong><button type="button" className={styles.drawerClose} onClick={onClose}>关闭</button></div>
      <div className={styles.drawerBody}>{drawer.mode === "materials" ? <MaterialSummary summary={materialSummary} /> : selection ? <>
        <div className={styles.drawerCard}><h3>选中内容</h3><p>{selection.selectedText}</p></div>
        <div className={styles.drawerCard}><h3>{drawer.mode === "example" ? "你想要哪种例子？" : "你具体不懂哪里？"}</h3><textarea value={question} placeholder={drawer.mode === "example" ? "可选：比如“用工程实现举例”。不填则使用默认例子。" : "可选：比如“这句话和上一句有什么关系？” 不填则使用默认解释。"} onChange={(event) => setQuestion(event.target.value)} /><div className={styles.drawerActions}><button className={`${styles.smallButton} ${styles.primaryButton}`} onClick={() => confirm(false)}>{drawer.mode === "example" ? "生成例子" : "生成解释"}</button><button className={styles.smallButton} onClick={() => confirm(true)}>使用默认</button></div><div className={styles.actionHint}>只有点击生成或使用默认后，才会保留高亮并记录到阅读素材。</div></div>
        <div className={styles.drawerCard}><h3>{generated ? (drawer.mode === "example" ? "举例说明" : "解释") : "等待生成"}</h3><p>{generated || "你可以补充自己的疑问，也可以直接使用默认。未生成前，这次选择不会被保留为高亮。"}</p></div>
      </> : null}</div>
    </aside>
  )
}

function MaterialSummary({ summary }: { summary: ReturnType<typeof makeMaterialSummary> }) {
  return <>
    <div className={styles.drawerCard}><h3>给后台 Agent 的素材</h3><p>笔记、解释请求、举例请求、标记不懂都会记录。后续后台 Agent 可以基于这些素材生成完整笔记、困惑点列表和个性化复习建议。</p></div>
    <div className={styles.drawerCard}><h3>统计</h3><ul><li>笔记：{summary.stats.noteCount}</li><li>解释：{summary.stats.explainedCount}</li><li>举例：{summary.stats.exampledCount}</li><li>不懂：{summary.stats.confusedCount}</li></ul></div>
    <div className={styles.drawerCard}><h3>选中内容与读者输入</h3>{summary.selections.length ? summary.selections.slice().reverse().map((selection) => <article key={selection.id} className={`${styles.materialItem} ${selection.confused ? styles.confusedItem : selection.explained ? styles.explainItem : selection.exampled ? styles.exampleItem : ""}`}><small>{selection.sectionTitle} / {selection.paragraphId}{selection.noteText.trim() ? " · 笔记" : ""}{selection.explained ? " · 请求解释" : ""}{selection.exampled ? " · 请求举例" : ""}{selection.confused ? " · 标记不懂" : ""}</small><p><b>原文：</b>{selection.selectedText}</p>{selection.noteText.trim() ? <p><b>笔记：</b>{selection.noteText}</p> : null}{selection.explainQuestion.trim() ? <p><b>解释疑问：</b>{selection.explainQuestion}</p> : null}{selection.exampleQuestion.trim() ? <p><b>举例需求：</b>{selection.exampleQuestion}</p> : null}</article>) : <p className={styles.mutedText}>还没有素材。</p>}</div>
  </>
}

function floatingLayerStyle(x: number, y: number, width: number, height: number, padding: number): CSSProperties {
  if (typeof window === "undefined") {
    return { left: Math.max(padding, x), top: Math.max(padding, y) }
  }
  return {
    left: clamp(x, padding, window.innerWidth - width),
    top: clamp(y, padding, window.innerHeight - height),
  }
}
