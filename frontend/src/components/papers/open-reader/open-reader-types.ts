import type { Locale, PaperReaderPayload, PaperSection } from "@/lib/papers/types"

export type ReaderTheme = "light" | "warm" | "dark"
export type ReaderAssistMode = "explain" | "example" | "materials"

export type ReaderSelectionStatus =
  | "temp"
  | "has_note"
  | "explained"
  | "exampled"
  | "confused"

export interface ReaderSettings {
  fontSize: number
  contentWidth: number
  theme: ReaderTheme
  drawerWidth: number
  layoutVersion: number
}

export interface ReaderParagraph {
  id: string
  paperId: string
  sectionId: string
  sectionTitle: string
  sectionType: PaperSection["sectionType"]
  index: number
  text: string
  summary?: string
  pageStart?: number
  pageEnd?: number
}

export interface ReaderTocItem {
  id: string
  title: string
  sectionType: PaperSection["sectionType"]
  paragraphCount: number
}

export interface ReaderSelection {
  id: string
  paperId: string
  sectionId: string
  sectionTitle: string
  paragraphId: string
  selectedText: string
  surroundingText: string
  startOffset: number
  endOffset: number
  noteText: string
  explainQuestion: string
  exampleQuestion: string
  explained: boolean
  exampled: boolean
  confused: boolean
  createdAt: string
  updatedAt: string
}

export type ReaderEventType =
  | "selection_created"
  | "selection_discarded"
  | "note_updated"
  | "explanation_generated"
  | "example_generated"
  | "confusion_marked"
  | "confusion_unmarked"
  | "reader_settings_changed"
  | "drawer_resized"
  | "toc_navigated"

export interface ReaderEvent {
  id: string
  type: ReaderEventType
  paperId: string
  selectionId?: string
  paragraphId?: string
  sectionId?: string
  selectedText?: string
  surroundingText?: string
  payload?: Record<string, unknown>
  createdAt: string
}

export interface ReaderMaterialSummary {
  paperId: string
  selections: ReaderSelection[]
  events: ReaderEvent[]
  stats: {
    noteCount: number
    explainedCount: number
    exampledCount: number
    confusedCount: number
  }
}

export interface OpenReaderPageProps {
  reader: PaperReaderPayload
  locale: Locale
  backHref?: string
}

export interface SelectionMenuState {
  selectionId: string
  x: number
  y: number
}

export interface NotePopoverState {
  selectionId: string
  x: number
  y: number
}

export interface DrawerState {
  mode: ReaderAssistMode
  selectionId?: string
}
