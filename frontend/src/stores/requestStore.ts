import { create } from 'zustand'

/** One completed OK request, as shown in the browse status bar (spec §5.4). */
export interface LastRequest {
  method: string
  path: string
  ms: number
  requestId: string
}

interface RequestState {
  lastRequest: LastRequest | null
  set: (last: LastRequest) => void
  clear: () => void
}

export const useRequestStore = create<RequestState>((set) => ({
  lastRequest: null,
  set: (last) => set({ lastRequest: last }),
  clear: () => set({ lastRequest: null }),
}))
