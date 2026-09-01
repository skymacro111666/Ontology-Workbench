import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import AppShell from './AppShell'
import { AuthProvider, LAST_OID_KEY, TOKEN_KEY } from '../auth/AuthContext'
import { api } from '../api/client'
import { ThemeProvider } from '../theme/ThemeProvider'
import { useUiStore } from '../stores/uiStore'

vi.mock('../api/client', () => ({
  api: {
    get: vi.fn(async () => ({ items: [], total: 0 })),
    download: vi.fn(async () => 'mini.jsonld'),
  },
  ApiErr: class extends Error {},
}))

// Vitest globals are off, so RTL auto-cleanup never registers — the tree (and
// the shared uiStore's opened dialog) would leak into any later test.
afterEach(() => {
  cleanup()
  localStorage.clear()
  useUiStore.setState({
    browseView: 'graph',
    importOpen: false,
    blankOpen: false,
    sourceDirty: false,
    pendingView: null,
    sourceSaveFn: null,
  })
})

it('renders nav and opens the import dialog', async () => {
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
  await userEvent.click(screen.getByRole('button', { name: '文件 ▾' }))
  await userEvent.click(await screen.findByText('导入文件…'))
  expect(await screen.findByRole('dialog')).toBeTruthy()
})

it('logs out via the account menu (name now matches the assertion)', async () => {
  localStorage.setItem(TOKEN_KEY, 'tok')
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
  await userEvent.click(screen.getByRole('button', { name: /菜单/ }))
  await userEvent.click(await screen.findByText('退出登录'))
  await waitFor(() => expect(localStorage.getItem(TOKEN_KEY)).toBeNull())
})

it('renders the router Outlet when no children are given (production branch)', () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={['/']}>
          <AuthProvider>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/" element={<div>outlet content</div>} />
              </Route>
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
  expect(screen.getByText('outlet content')).toBeTruthy()
})

it('export menu downloads the current ontology in the picked RDF format', async () => {
  localStorage.setItem(LAST_OID_KEY, 'oid-1')
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

  await userEvent.click(screen.getByRole('button', { name: '文件 ▾' }))
  // The exports live one level down: hover opens the 导出 submenu.
  await userEvent.hover(await screen.findByText('导出'))
  expect(await screen.findByText('Turtle (.ttl)')).toBeTruthy()
  expect(screen.getByText('RDF/XML (.rdf)')).toBeTruthy()
  await userEvent.click(screen.getByText('JSON-LD (.jsonld)'))

  await waitFor(() =>
    expect(vi.mocked(api.download)).toHaveBeenCalledWith(
      '/api/ontologies/oid-1/export/file?format=json-ld',
      'ontology',
    ),
  )
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

it('opens the blank-create dialog from the file menu', async () => {
  shell('/')
  await userEvent.click(screen.getByRole('button', { name: '文件 ▾' }))
  await userEvent.click(await screen.findByText('新建空白本体…'))
  expect(await screen.findByRole('dialog')).toBeTruthy()
  expect(screen.getByText('新建空白本体')).toBeTruthy()
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

it('guards switching away from dirty text view', async () => {
  const saveFn = vi.fn(async () => true)
  useUiStore.setState({
    browseView: 'text',
    sourceDirty: true,
    sourceSaveFn: saveFn,
    pendingView: null,
  })
  shell('/browse/oid-1')

  // Cancel keeps the text view.
  await userEvent.click(screen.getByRole('radio', { name: /图形/ }))
  expect(await screen.findByRole('alertdialog')).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(useUiStore.getState().browseView).toBe('text')
  expect(useUiStore.getState().pendingView).toBeNull()

  // Discard switches without saving.
  await userEvent.click(screen.getByRole('radio', { name: /图形/ }))
  await userEvent.click(await screen.findByRole('button', { name: '放弃并切换' }))
  expect(useUiStore.getState().browseView).toBe('graph')

  // Save-and-switch calls the registered save; success switches.
  useUiStore.setState({ browseView: 'text' })
  await userEvent.click(screen.getByRole('radio', { name: /图形/ }))
  await userEvent.click(await screen.findByRole('button', { name: '保存并切换' }))
  await waitFor(() => expect(useUiStore.getState().browseView).toBe('graph'))
  expect(saveFn).toHaveBeenCalledTimes(1)

  // A failing save keeps the text view (error surfaces in SourceView).
  const failFn = vi.fn(async () => false)
  useUiStore.setState({ browseView: 'text', sourceSaveFn: failFn })
  await userEvent.click(screen.getByRole('radio', { name: /文本/ }))
  await userEvent.click(screen.getByRole('radio', { name: /图形/ }))
  await userEvent.click(await screen.findByRole('button', { name: '保存并切换' }))
  await waitFor(() => expect(failFn).toHaveBeenCalledTimes(1))
  expect(useUiStore.getState().browseView).toBe('text')
})

it('switches freely when the text view is clean', async () => {
  shell('/browse/oid-1')
  await userEvent.click(screen.getByRole('radio', { name: /文本/ }))
  expect(useUiStore.getState().browseView).toBe('text')
  expect(screen.queryByRole('alertdialog')).toBeNull()
})
