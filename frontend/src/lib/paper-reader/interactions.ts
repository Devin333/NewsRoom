import type { ReaderBlockTarget } from "@/lib/papers/types"
import type { PaperBlock } from "@/lib/paper-reader/types"

export function targetForPaperBlock(block: PaperBlock): ReaderBlockTarget {
  return {
    targetType: block.type === "heading" ? "paragraph" : block.type,
    blockId: block.id,
    assetId: block.assetId,
    sectionId: block.sectionId,
    paragraphId: block.type === "paragraph" || block.type === "heading" ? block.id : undefined,
    pageNumber: block.pageNumber ?? block.source?.pageNumber,
    sourceBox: block.source?.bbox,
    metadata: {
      label: block.label,
      caption: block.caption,
      blockType: block.type,
    },
  }
}
