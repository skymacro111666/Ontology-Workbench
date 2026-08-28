import { create } from 'zustand'

/** Workspace content mode for Zone 2 (graph canvas vs source text). */
export type BrowseView = 'graph' | 'text'

/** Save capability SourceView registers for the switch-guard dialog:
 *  resolves true when the edit was saved, false when it failed. */
export type SourceSaveFn = () => Promise<boolean>

/** What the A2 entity dialogs are editing (canvas right-click opens one). */
export type EntityDialogMode =
  | 'class'
  | 'subclass'
  | 'objectProperty'
  | 'dataProperty'
  | 'editClass'
  | 'editProperty'
  | 'delete'

export interface EntityDialogState {
  mode: EntityDialogMode
  /** Right-clicked class: pre-fills subclass parent / property domain. */
  parent?: string
  /** Entity IRI for the edit modes. */
  eid?: string
}

/** Cross-component UI state (import dialog flag, workspace view mode). */
export const useUiStore = create<{
  importOpen: boolean
  setImportOpen: (open: boolean) => void
  browseView: BrowseView
  setBrowseView: (view: BrowseView) => void
  /** Sidebar collapse (rail mode): collapsed panels stay mounted, hidden. */
  leftCollapsed: boolean
  setLeftCollapsed: (collapsed: boolean) => void
  rightCollapsed: boolean
  setRightCollapsed: (collapsed: boolean) => void
  sourceDirty: boolean
  setSourceDirty: (dirty: boolean) => void
  pendingView: BrowseView | null
  setPendingView: (view: BrowseView | null) => void
  sourceSaveFn: SourceSaveFn | null
  registerSourceSave: (fn: SourceSaveFn | null) => void
  entityDialog: EntityDialogState | null
  setEntityDialog: (s: EntityDialogState | null) => void
}>((set) => ({
  importOpen: false,
  setImportOpen: (importOpen) => set({ importOpen }),
  browseView: 'graph',
  setBrowseView: (browseView) => set({ browseView }),
  leftCollapsed: false,
  setLeftCollapsed: (leftCollapsed) => set({ leftCollapsed }),
  rightCollapsed: false,
  setRightCollapsed: (rightCollapsed) => set({ rightCollapsed }),
  sourceDirty: false,
  setSourceDirty: (sourceDirty) => set({ sourceDirty }),
  pendingView: null,
  setPendingView: (pendingView) => set({ pendingView }),
  sourceSaveFn: null,
  registerSourceSave: (sourceSaveFn) => set({ sourceSaveFn }),
  entityDialog: null,
  setEntityDialog: (entityDialog) => set({ entityDialog }),
}))
