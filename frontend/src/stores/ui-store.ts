import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"

export type ThemeMode = "light" | "dark"

type UiState = {
  sidebarCollapsed: boolean
  commandOpen: boolean
  rightPanelOpen: boolean
  theme: ThemeMode
  setSidebarCollapsed: (value: boolean) => void
  toggleSidebar: () => void
  setCommandOpen: (value: boolean) => void
  setRightPanelOpen: (value: boolean) => void
  setTheme: (theme: ThemeMode) => void
  toggleTheme: () => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      commandOpen: false,
      rightPanelOpen: true,
      theme: "light",
      setSidebarCollapsed: (value) => set({ sidebarCollapsed: value }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setCommandOpen: (value) => set({ commandOpen: value }),
      setRightPanelOpen: (value) => set({ rightPanelOpen: value }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" }))
    }),
    {
      name: "newsroom-ui",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        rightPanelOpen: state.rightPanelOpen,
        theme: state.theme
      })
    }
  )
)
