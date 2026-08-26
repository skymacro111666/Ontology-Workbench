import { create } from 'zustand'

/** Workspace content mode for Zone 2 (graph canvas vs source text). */
export type BrowseView = 'graph' | 'text'

/** Save capability SourceView registers for the switch-guard dialog:
 *  resolves true when the edit was saved, false when it failed. */
export type SourceSaveFn = () => Promise<boolean>

/** Cross-component UI state (import dialog flag, workspace view mode). */
export const useUiStore = create<{
  importOpen: boolean
  setImportOpen: (open: boolean) => void
  browseView: BrowseView
  setBrowseView: (view: BrowseView) => void
  sourceDirty: boolean
  setSourceDirty: (dirty: boolean) => void
  pendingView: BrowseView | null
  setPendingView: (view: BrowseView | null) => void
  sourceSaveFn: SourceSaveFn | null
  registerSourceSave: (fn: SourceSaveFn | null) => void
}>((set) => ({
  importOpen: false,
  setImportOpen: (importOpen) => set({ importOpen }),
  browseView: 'graph',
  setBrowseView: (browseView) => set({ browseView }),
  sourceDirty: false,
  setSourceDirty: (sourceDirty) => set({ sourceDirty }),
  pendingView: null,
  setPendingView: (pendingView) => set({ pendingView }),
  sourceSaveFn: null,
  registerSourceSave: (sourceSaveFn) => set({ sourceSaveFn }),
}))
