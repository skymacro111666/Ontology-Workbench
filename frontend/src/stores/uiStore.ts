import { create } from 'zustand'

/** Workspace content mode for Zone 2 (graph canvas vs source text). */
export type BrowseView = 'graph' | 'text'

/** Cross-component UI state (import dialog flag, workspace view mode). */
export const useUiStore = create<{
  importOpen: boolean
  setImportOpen: (open: boolean) => void
  browseView: BrowseView
  setBrowseView: (view: BrowseView) => void
}>((set) => ({
  importOpen: false,
  setImportOpen: (importOpen) => set({ importOpen }),
  browseView: 'graph',
  setBrowseView: (browseView) => set({ browseView }),
}))
