import { cleanup, render, waitFor } from '@testing-library/react'
import { toast } from 'sonner'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { ThemeProvider } from '../../theme/ThemeProvider'
import { Toaster } from './sonner'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
  // matchMedia comes from setup.ts and reads as light: the OS preference
  // disagrees with the forced-dark app below, which is the point.
})

afterEach(() => cleanup())

it('toast chrome follows the app theme, not the OS preference', async () => {
  // App forced dark while the OS stub stays light — the toaster must be
  // dark too, or dark mode shows light-chrome toasts (backlog Minor#3).
  localStorage.setItem('ow_theme', 'dark')
  render(
    <ThemeProvider>
      <Toaster />
    </ThemeProvider>,
  )
  // The themed <ol> only mounts once a toast exists.
  toast('hello')
  await waitFor(() => {
    expect(document.querySelector('[data-sonner-toaster]')).not.toBeNull()
  })
  const toaster = document.querySelector('[data-sonner-toaster]')!
  expect(toaster.getAttribute('data-sonner-theme')).toBe('dark')
})
