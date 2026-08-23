import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { ThemeProvider, useTheme } from './ThemeProvider'

function probe() {
  return renderHook(() => useTheme(), { wrapper: ThemeProvider })
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

// Vitest globals are off, so RTL auto-cleanup never registers — without this,
// each test's ThemeProvider stays mounted and keeps writing to <html>.
afterEach(() => cleanup())

it('defaults to system and resolves via matchMedia', () => {
  window.matchMedia = (q: string) =>
    ({ matches: q.includes('dark'), media: q, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => true }) as MediaQueryList
  const { result } = probe()
  expect(result.current.theme).toBe('system')
  expect(result.current.resolved).toBe('dark')
  expect(document.documentElement.classList.contains('dark')).toBe(true)
})

it('persists explicit choice and applies it', () => {
  window.matchMedia = () => ({ matches: false, media: '', addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => true }) as MediaQueryList
  const { result } = probe()
  act(() => result.current.setTheme('light'))
  expect(localStorage.getItem('ow_theme')).toBe('light')
  expect(result.current.resolved).toBe('light')
})
