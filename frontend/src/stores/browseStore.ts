import { create } from 'zustand'

/** Content-area view mode; 'split'/'graph' arrive with the M3 graph work. */
export type ViewMode = 'detail' | 'split' | 'graph'

interface BrowseState {
  selectedEid: string | null
  viewMode: ViewMode
  setSelected: (eid: string | null) => void
  setViewMode: (mode: ViewMode) => void
}

/** Shared browse state: what is selected and how the content area shows it. */
export const useBrowseStore = create<BrowseState>((set) => ({
  selectedEid: null,
  viewMode: 'detail',
  setSelected: (selectedEid) => set({ selectedEid }),
  setViewMode: (viewMode) => set({ viewMode }),
}))
