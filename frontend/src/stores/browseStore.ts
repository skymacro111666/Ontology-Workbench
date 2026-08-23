import { create } from 'zustand'

interface BrowseState {
  selectedEid: string | null
  /** Entity the tree should expand-reveal (search picks); null when handled. */
  revealEid: string | null
  setSelected: (eid: string | null) => void
  /** Select AND ask the class tree to expand the ancestor path. */
  reveal: (eid: string) => void
  clearReveal: () => void
}

/** Shared workspace state: what is selected (tree, canvas and inspector
 *  all follow it; the canvas is permanently the overview view). */
export const useBrowseStore = create<BrowseState>((set) => ({
  selectedEid: null,
  revealEid: null,
  setSelected: (selectedEid) => set({ selectedEid }),
  reveal: (eid) => set({ selectedEid: eid, revealEid: eid }),
  clearReveal: () => set({ revealEid: null }),
}))
