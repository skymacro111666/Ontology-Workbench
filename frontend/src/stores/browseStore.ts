import { create } from 'zustand'

/** Content-area view mode; 'split'/'graph' arrive with the M3 graph work. */
export type ViewMode = 'detail' | 'split' | 'graph'

interface BrowseState {
  selectedEid: string | null
  viewMode: ViewMode
  /** Entity the tree should expand-reveal (search picks); null when handled. */
  revealEid: string | null
  /** Entity whose TTL tab the central detail should open (inspector action). */
  ttlFocusEid: string | null
  /** Bumped on every TTL request so repeated asks re-trigger the open. */
  ttlNonce: number
  setSelected: (eid: string | null) => void
  setViewMode: (mode: ViewMode) => void
  /** Select AND ask the class tree to expand the ancestor path. */
  reveal: (eid: string) => void
  clearReveal: () => void
  /** Ask the central EntityDetail to open this entity's TTL tab. */
  openTtl: (eid: string) => void
}

/** Shared browse state: what is selected and how the content area shows it. */
export const useBrowseStore = create<BrowseState>((set) => ({
  selectedEid: null,
  viewMode: 'detail',
  revealEid: null,
  ttlFocusEid: null,
  ttlNonce: 0,
  setSelected: (selectedEid) => set({ selectedEid }),
  setViewMode: (viewMode) => set({ viewMode }),
  reveal: (eid) => set({ selectedEid: eid, revealEid: eid }),
  clearReveal: () => set({ revealEid: null }),
  openTtl: (eid) => set((s) => ({ ttlFocusEid: eid, ttlNonce: s.ttlNonce + 1 })),
}))
