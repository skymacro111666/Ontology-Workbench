import { configure } from '@testing-library/react'
import { vi } from 'vitest'
import '../i18n'

// The import above initializes i18next for every test file — components use
// useTranslation without touching main.tsx. Test language is pinned to zh by
// src/i18n/index.ts (MODE === 'test' passes lng directly; jsdom's navigator
// would otherwise resolve en-US). Do not change language from tests except in
// LangToggle's own tests.

// jsdom renders slowly; give async queries headroom.
configure({ asyncUtilTimeout: 10000 })

// jsdom lacks matchMedia; ThemeProvider's prefers-color-scheme probe and
// sonner's system-theme resolution read it.
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

// jsdom lacks ResizeObserver; useContainerHeight (ClassTree row virtualization) needs it.
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
