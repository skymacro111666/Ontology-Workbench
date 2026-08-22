import { create } from 'zustand'

/** Cross-component UI state (import dialog open flag). */
export const useUiStore = create<{
  importOpen: boolean
  setImportOpen: (open: boolean) => void
}>((set) => ({ importOpen: false, setImportOpen: (importOpen) => set({ importOpen }) }))
