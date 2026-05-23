"use client"

import { create } from "zustand"

export type InspectorTab = "logs" | "tools" | "memory" | "artifacts" | "quality" | "errors"

type RunInspectorState = {
  selectedNodeId?: string
  selectedStepId?: string
  activeTab: InspectorTab
  setSelectedNodeId: (id?: string) => void
  setSelectedStepId: (id?: string) => void
  selectStep: (nodeId?: string, stepId?: string) => void
  setActiveTab: (tab: InspectorTab) => void
}

export const useRunInspectorStore = create<RunInspectorState>((set) => ({
  selectedNodeId: undefined,
  selectedStepId: undefined,
  activeTab: "logs",
  setSelectedNodeId: (id) => set({ selectedNodeId: id }),
  setSelectedStepId: (id) => set({ selectedStepId: id }),
  selectStep: (nodeId, stepId) => set({ selectedNodeId: nodeId, selectedStepId: stepId }),
  setActiveTab: (tab) => set({ activeTab: tab })
}))
