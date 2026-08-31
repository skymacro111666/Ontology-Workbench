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

/** What the B2 instance dialogs are editing (canvas / inspector open one). */
export interface InstanceDialogState {
  mode: 'create' | 'delete'
  /** Class eid: pre-fills the create type list; unused for delete. */
  parent?: string
  /** Instance IRI for delete. */
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
  instanceDialog: InstanceDialogState | null
  setInstanceDialog: (s: InstanceDialogState | null) => void
  /** Instance eid that should land straight in edit mode: set right after
   *  creation (spec §0) and by the canvas 编辑实例 context action; the
   *  detail consumes it and clears the flag. */
  instanceAutoEdit: string | null
  setInstanceAutoEdit: (eid: string | null) => void
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
  instanceDialog: null,
  setInstanceDialog: (instanceDialog) => set({ instanceDialog }),
  instanceAutoEdit: null,
  setInstanceAutoEdit: (instanceAutoEdit) => set({ instanceAutoEdit }),
}))
