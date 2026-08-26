import { configure } from '@testing-library/react'
import { vi } from 'vitest'

// This environment renders AntD slowly; give async queries headroom.
configure({ asyncUtilTimeout: 10000 })

// jsdom lacks matchMedia; AntD's responsive observer and useSystemTheme need it.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
})

// jsdom lacks ResizeObserver; AntD's virtual list and grid components need it.
class ResizeObserverStub implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver

// jsdom's Range has no geometry (no layout engine); CodeMirror's measure
// pass reads getClientRects on ranges and would crash on it. Empty rects
// let CM fall back to its built-in default metrics.
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = function (): DOMRectList {
    return [] as unknown as DOMRectList
  }
  Range.prototype.getBoundingClientRect = function (): DOMRect {
    return new DOMRect(0, 0, 0, 0)
  }
}
