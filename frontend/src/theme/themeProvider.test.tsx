import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { ThemeProvider, useTheme } from './ThemeProvider'

function probe() {
  return renderHook(() => useTheme(), { wrapper: ThemeProvider })
}

/** Full MediaQueryList stub; `dark` sets the initial match, `onChange`
 *  captures the 'change' listener so a test can fire it. */
function stubMatchMedia(dark: boolean, onChange?: (l: (e: { matches: boolean }) => void) => void) {
  window.matchMedia = ((q: string) =>
    ({
      matches: dark && q.includes('dark'),
      media: q,
      addEventListener: (_: string, l: unknown) => onChange?.(l as (e: { matches: boolean }) => void),
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => true,
    })) as unknown as typeof window.matchMedia
}

// setup.ts installs a matchMedia stub for the whole file; per-test overrides
// must not leak into later tests, so restore the baseline after each.
const baselineMatchMedia = window.matchMedia

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

// Vitest globals are off, so RTL auto-cleanup never registers — without this,
// each test's ThemeProvider stays mounted and keeps writing to <html>.
afterEach(() => {
  cleanup()
  window.matchMedia = baselineMatchMedia
})

it('defaults to system and resolves via matchMedia', () => {
  stubMatchMedia(true)
  const { result } = probe()
  expect(result.current.theme).toBe('system')
  expect(result.current.resolved).toBe('dark')
  expect(document.documentElement.classList.contains('dark')).toBe(true)
})

it('persists explicit choice and applies it', () => {
  stubMatchMedia(false)
  const { result } = probe()
  act(() => result.current.setTheme('light'))
  expect(localStorage.getItem('ow_theme')).toBe('light')
  expect(result.current.resolved).toBe('light')
})

it('tracks live OS preference changes while on system', () => {
  let change: ((e: { matches: boolean }) => void) | undefined
  stubMatchMedia(false, (l) => {
    change = l
  })
  const { result } = probe()
  expect(result.current.resolved).toBe('light')
  act(() => change!({ matches: true }))
  expect(result.current.resolved).toBe('dark')
  expect(document.documentElement.classList.contains('dark')).toBe(true)
})

it('throws when useTheme runs outside the provider', () => {
  expect(() => renderHook(() => useTheme())).toThrow(/within ThemeProvider/)
})
