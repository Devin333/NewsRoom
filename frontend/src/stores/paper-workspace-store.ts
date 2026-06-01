import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"

export type PaperWorkspaceList = "readingList" | "compare" | "later"

type PaperWorkspaceState = {
  readingList: string[]
  compare: string[]
  later: string[]
  hasPaper: (list: PaperWorkspaceList, paperId: string) => boolean
  togglePaper: (list: PaperWorkspaceList, paperId: string) => void
  clear: () => void
}

const emptyLists = {
  readingList: [],
  compare: [],
  later: []
}

export const usePaperWorkspaceStore = create<PaperWorkspaceState>()(
  persist(
    (set, get) => ({
      ...emptyLists,
      hasPaper: (list, paperId) => get()[list].includes(paperId),
      togglePaper: (list, paperId) => {
        set((state) => {
          const current = state[list]
          const next = current.includes(paperId)
            ? current.filter((id) => id !== paperId)
            : [...current, paperId]
          return { [list]: next } as Pick<PaperWorkspaceState, PaperWorkspaceList>
        })
      },
      clear: () => set(emptyLists)
    }),
    {
      name: "newsroom-paper-workspace",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        readingList: state.readingList,
        compare: state.compare,
        later: state.later
      })
    }
  )
)
