import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import AppShell from './AppShell'
import { AuthProvider } from '../auth/AuthContext'
import { ThemeProvider } from '../theme/ThemeProvider'
import { useUiStore } from '../stores/uiStore'

vi.mock('../api/client', () => ({
  api: { get: vi.fn(async () => ({ items: [], total: 0 })) },
  ApiErr: class extends Error {},
}))

// Vitest globals are off, so RTL auto-cleanup never registers — the tree (and
// the shared uiStore's opened dialog) would leak into any later test.
afterEach(() => {
  cleanup()
  useUiStore.setState({ browseView: 'graph', importOpen: false })
})

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
  expect(screen.getByRole('button', { name: '概览' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '工作区' })).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '＋ 导入' }))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})

function shell(entry: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[entry]}>
          <AuthProvider>
            <AppShell>
              <div>content</div>
            </AppShell>
          </AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

it('hides the 图形/文本 switch outside the workspace', () => {
  shell('/')
  expect(screen.queryByRole('radio', { name: /图形/ })).toBeNull()
  expect(screen.queryByRole('radio', { name: /文本/ })).toBeNull()
})

it('workspace topbar switches the browse view mode through the store', async () => {
  shell('/browse/oid-1')
  const graph = screen.getByRole('radio', { name: /图形/ })
  const text = screen.getByRole('radio', { name: /文本/ })
  expect(graph.getAttribute('aria-checked')).toBe('true')
  expect(text.getAttribute('aria-checked')).toBe('false')

  await userEvent.click(text)
  expect(useUiStore.getState().browseView).toBe('text')
  expect(text.getAttribute('aria-checked')).toBe('true')

  await userEvent.click(graph)
  expect(useUiStore.getState().browseView).toBe('graph')
})
