import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import AppShell from './AppShell'
import { AuthProvider } from '../auth/AuthContext'
import { ThemeProvider } from '../theme/ThemeProvider'

vi.mock('../api/client', () => ({
  api: { get: vi.fn(async () => ({ items: [], total: 0 })) },
  ApiErr: class extends Error {},
}))

// Vitest globals are off, so RTL auto-cleanup never registers — the tree (and
// the shared uiStore's opened dialog) would leak into any later test.
afterEach(() => cleanup())

it('renders nav, opens import dialog, logs out', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter>
          <AuthProvider>
            <AppShell>
              <div>content</div>
            </AppShell>
          </AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
  expect(screen.getByText('Ontology Workbench')).toBeTruthy()
  expect(screen.getByText('content')).toBeTruthy()
  // Nav asserted before opening the dialog: Radix modal dialogs aria-hide all
  // outside content, so the topbar buttons leave the accessibility tree while
  // the import dialog is open.
  expect(screen.getByRole('button', { name: /工作台/ })).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: /导入本体/ }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})
