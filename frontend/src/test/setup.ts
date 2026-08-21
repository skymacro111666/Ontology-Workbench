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
