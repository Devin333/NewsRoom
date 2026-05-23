import { create } from "zustand"
import type { NewsFilters } from "@/types/news"

type FilterState = {
  newsDraft: NewsFilters
  setNewsDraft: (filters: NewsFilters) => void
  resetNewsDraft: () => void
}

export const useFilterStore = create<FilterState>((set) => ({
  newsDraft: {},
  setNewsDraft: (filters) => set({ newsDraft: filters }),
  resetNewsDraft: () => set({ newsDraft: {} })
}))
