import { create } from 'zustand'

/** Workspace content mode for Zone 2 (graph canvas vs source text). */
export type BrowseView = 'graph' | 'text' | 'query' | 'validate' | 'registry'

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

/** Cross-component UI state (import/blank-create/draft/AI-settings dialog
 *  flags, view mode). */
export const useUiStore = create<{
  importOpen: boolean
  setImportOpen: (open: boolean) => void
  blankOpen: boolean
  setBlankOpen: (open: boolean) => void
  exportOpen: boolean
  setExportOpen: (open: boolean) => void
  draftOpen: boolean
  setDraftOpen: (open: boolean) => void
  aiSettingsOpen: boolean
  setAiSettingsOpen: (open: boolean) => void
  aiChatOpen: boolean
  setAiChatOpen: (open: boolean) => void
  browseView: BrowseView
  setBrowseView: (view: BrowseView) => void
  /** Sidebar collapse (rail mode): collapsed panels stay mounted, hidden. */
  leftCollapsed: boolean
  setLeftCollapsed: (collapsed: boolean) => void
  rightCollapsed: boolean
  setRightCollapsed: (collapsed: boolean) => void
  /** Pre-drawer sidebar state while the AI drawer auto-collapses them;
   *  a side the user re-toggles mid-chat goes null there (choice stands).
   *  null overall = the drawer is not managing the sidebars. */
  aiChatSavedCollapse: { left: boolean | null; right: boolean | null } | null
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
}>((set, get) => {
  /** While the drawer is showing (graph mode) both sidebars collapse so the
   *  canvas keeps its width (方案A); they restore when it stops showing,
   *  except sides the user re-toggled in between — their choice stands. */
  const syncAiCollapse = () => {
    const s = get()
    const showing = s.aiChatOpen && s.browseView === 'graph'
    if (showing && s.aiChatSavedCollapse === null) {
      set({
        aiChatSavedCollapse: { left: s.leftCollapsed, right: s.rightCollapsed },
        leftCollapsed: true,
        rightCollapsed: true,
      })
    } else if (!showing && s.aiChatSavedCollapse !== null) {
      const saved = s.aiChatSavedCollapse
      set({
        aiChatSavedCollapse: null,
        leftCollapsed: saved.left ?? s.leftCollapsed,
        rightCollapsed: saved.right ?? s.rightCollapsed,
      })
    }
  }

  return {
    importOpen: false,
    setImportOpen: (importOpen) => set({ importOpen }),
    blankOpen: false,
    setBlankOpen: (blankOpen) => set({ blankOpen }),
    exportOpen: false,
    setExportOpen: (exportOpen) => set({ exportOpen }),
    draftOpen: false,
    setDraftOpen: (draftOpen) => set({ draftOpen }),
    aiSettingsOpen: false,
    setAiSettingsOpen: (aiSettingsOpen) => set({ aiSettingsOpen }),
    aiChatOpen: false,
    setAiChatOpen: (aiChatOpen) => {
      set({ aiChatOpen })
      syncAiCollapse()
    },
    aiChatSavedCollapse: null,
    browseView: 'graph',
    setBrowseView: (browseView) => {
      set({ browseView })
      syncAiCollapse()
    },
    leftCollapsed: false,
    setLeftCollapsed: (leftCollapsed) =>
      set((s) => ({
        leftCollapsed,
        ...(s.aiChatSavedCollapse && { aiChatSavedCollapse: { ...s.aiChatSavedCollapse, left: null } }),
      })),
    rightCollapsed: false,
    setRightCollapsed: (rightCollapsed) =>
      set((s) => ({
        rightCollapsed,
        ...(s.aiChatSavedCollapse && { aiChatSavedCollapse: { ...s.aiChatSavedCollapse, right: null } }),
      })),
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
  }
})
