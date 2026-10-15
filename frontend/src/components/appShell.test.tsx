import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import AppShell from './AppShell'
import { AuthProvider, LAST_OID_KEY, TOKEN_KEY } from '../auth/AuthContext'
import { api, ApiErr } from '../api/client'
import { ThemeProvider } from '../theme/ThemeProvider'
import { useUiStore } from '../stores/uiStore'

vi.mock('../api/client', () => ({
  api: {
    // DraftFromDbDialog (mounted by the shell) expects array payloads for
    // its connection/engine lists; the switcher still gets {items,total}.
    get: vi.fn(async (url: string) =>
      String(url).includes('/db-connections') ? [] : { items: [], total: 0 },
    ),
    download: vi.fn(async () => 'mini.jsonld'),
    downloadBinary: vi.fn(async () => ({ name: 'shop.r2rml.ttl', truncated: false })),
  },
  ApiErr: class extends Error {},
}))

// Bare toast() calls (the oid guard) cannot be spied on an ESM namespace;
// hand tests a callable mock carrying the usual level methods.
vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
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
    exportOpen: false,
    draftOpen: false,
    aiSettingsOpen: false,
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

it('account menu carries the agent-token settings entry', async () => {
  shell('/')
  await userEvent.click(screen.getByRole('button', { name: /菜单/ }))
  const item = await screen.findByText('Agent 令牌')
  expect(item).toBeTruthy()
  // Clicking runs the navigate handler and closes the menu.
  await userEvent.click(item)
  expect(screen.queryByText('退出登录')).toBeNull()
})

it('account menu carries 数据库设置 directly below AI 设置, navigating to /db-connections', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Probe = () => {
    const loc = useLocation()
    return <span data-testid="loc">{loc.pathname}</span>
  }
  render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={['/']}>
          <AuthProvider>
            <Probe />
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/" element={<div>home</div>} />
              </Route>
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
  await userEvent.click(screen.getByRole('button', { name: /菜单/ }))
  const db = await screen.findByText('数据库设置')
  // Position contract: the entry sits directly below AI 设置.
  const ai = screen.getByText('AI 设置')
  expect(db.compareDocumentPosition(ai) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()

  await userEvent.click(db)
  await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/db-connections'))
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
      '/api/v1/ontologies/oid-1/export/file?format=json-ld',
      'ontology',
    ),
  )
})

it('docs-site export menu item opens the floating export dialog', async () => {
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
  await userEvent.hover(await screen.findByText('导出'))
  await userEvent.click(await screen.findByText('导出文档站'))

  // The floating dialog carries the export form — no route navigation.
  expect(await screen.findByLabelText('输出目录（可选）')).toBeTruthy()
  expect(useUiStore.getState().exportOpen).toBe(true)
})

it('docs-site export menu guards on a chosen ontology before opening', async () => {
  const toastSpy = (await import('sonner')).toast as unknown as ReturnType<typeof vi.fn>
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
  await userEvent.hover(await screen.findByText('导出'))
  await userEvent.click(await screen.findByText('导出文档站'))

  expect(toastSpy).toHaveBeenCalledWith('先选择一个本体')
  expect(useUiStore.getState().exportOpen).toBe(false)
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

it('mounts the R2RML view button on /browse only (the page lives there)', () => {
  const { unmount } = shell('/browse/oid-1')
  expect(screen.getByRole('button', { name: 'R2RML' })).toBeTruthy()
  unmount()
  shell('/graph/oid-1')
  // /graph never hosts the workbench: the button stays browse-only.
  expect(screen.queryByRole('button', { name: 'R2RML' })).toBeNull()
})

it('toggles r2rmlOpen from the R2RML button', async () => {
  /** 按钮 toggle:点击置 open(aria-pressed 跟随),再点收回。 */
  shell('/browse/oid-1')
  const btn = screen.getByRole('button', { name: 'R2RML' })
  expect(btn.getAttribute('aria-pressed')).toBe('false')
  await userEvent.click(btn)
  expect(useUiStore.getState().r2rmlOpen).toBe(true)
  expect(screen.getByRole('button', { name: 'R2RML' }).getAttribute('aria-pressed')).toBe('true')
  await userEvent.click(screen.getByRole('button', { name: 'R2RML' }))
  expect(useUiStore.getState().r2rmlOpen).toBe(false)
})

it('blocks view switch while r2rml dirty; confirming discards and closes', async () => {
  /** dirty 时切视图先弹确认;确认后 r2rmlOpen 关、dirty 清、视图切换。 */
  shell('/browse/oid-1')
  useUiStore.setState({ r2rmlOpen: true, r2rmlDirty: true })
  await userEvent.click(screen.getByRole('radio', { name: /文本/ }))
  expect(useUiStore.getState().r2rmlOpen).toBe(true) // 未确认,不动
  await userEvent.click(await screen.findByRole('button', { name: /放弃修改/ }))
  expect(useUiStore.getState().r2rmlOpen).toBe(false)
  expect(useUiStore.getState().r2rmlDirty).toBe(false)
  expect(useUiStore.getState().browseView).toBe('text')
  useUiStore.setState({ r2rmlOpen: false, r2rmlDirty: false })
})

it('closes the workbench page on a clean view switch', async () => {
  /** 干净态切视图:工作台页即关(spec §6;与 dirty 路径对称)。 */
  shell('/browse/oid-1')
  useUiStore.setState({ r2rmlOpen: true, r2rmlDirty: false })
  await userEvent.click(screen.getByRole('radio', { name: /文本/ }))
  expect(useUiStore.getState().r2rmlOpen).toBe(false)
  expect(useUiStore.getState().browseView).toBe('text')
  useUiStore.setState({ r2rmlOpen: false, r2rmlDirty: false })
})

it('re-clicking the pressed view while the R2RML page is open returns to it', async () => {
  /** Radix single-toggle 点击已按下项发出空串;R2RML 页开着时应回到该视图
   *  而非无反应(browseView 停留在原值,图形仍显示为按下)。 */
  shell('/browse/oid-1')
  useUiStore.setState({ browseView: 'graph', r2rmlOpen: true, r2rmlDirty: false })
  await userEvent.click(screen.getByRole('radio', { name: /图形/ }))
  expect(useUiStore.getState().r2rmlOpen).toBe(false)
  expect(useUiStore.getState().browseView).toBe('graph')
  useUiStore.setState({ r2rmlOpen: false, r2rmlDirty: false })
})

it('re-clicking the pressed view while dirty routes through the discard guard', async () => {
  /** 同一交互的 dirty 分支:先弹确认,放弃修改后回到原视图。 */
  shell('/browse/oid-1')
  useUiStore.setState({ browseView: 'graph', r2rmlOpen: true, r2rmlDirty: true })
  await userEvent.click(screen.getByRole('radio', { name: /图形/ }))
  expect(useUiStore.getState().r2rmlOpen).toBe(true) // 未确认,不动
  await userEvent.click(await screen.findByRole('button', { name: /放弃修改/ }))
  expect(useUiStore.getState().r2rmlOpen).toBe(false)
  expect(useUiStore.getState().r2rmlDirty).toBe(false)
  expect(useUiStore.getState().browseView).toBe('graph')
  useUiStore.setState({ r2rmlOpen: false, r2rmlDirty: false })
})

it('opens the blank-create dialog from the file menu 新建 submenu', async () => {
  shell('/')
  await userEvent.click(screen.getByRole('button', { name: '文件 ▾' }))
  await userEvent.hover(await screen.findByText('新建'))
  await userEvent.click(await screen.findByText('新建空白本体…'))
  expect(await screen.findByRole('dialog')).toBeTruthy()
  expect(screen.getByText('新建空白本体')).toBeTruthy()
})

it('file menu 新建 ▸ 从数据库起草 sets the draft dialog flag', async () => {
  shell('/')
  await userEvent.click(screen.getByRole('button', { name: '文件 ▾' }))
  await userEvent.hover(await screen.findByText('新建'))
  await userEvent.click(await screen.findByText('从数据库起草本体…'))
  // The dialog itself mounts in a later task; the menu contract is the flag.
  expect(useUiStore.getState().draftOpen).toBe(true)
})

it('account menu carries the AI settings entry', async () => {
  shell('/')
  await userEvent.click(screen.getByRole('button', { name: /菜单/ }))
  await userEvent.click(await screen.findByText('AI 设置'))
  expect(useUiStore.getState().aiSettingsOpen).toBe(true)
})

it('workspace topbar switches the browse view mode through the store', async () => {
  shell('/browse/oid-1')
  const graph = screen.getByRole('radio', { name: /图形/ })
  const text = screen.getByRole('radio', { name: /文本/ })
  const query = screen.getByRole('radio', { name: /查询/ })
  expect(graph.getAttribute('aria-checked')).toBe('true')
  expect(text.getAttribute('aria-checked')).toBe('false')
  expect(query.getAttribute('aria-checked')).toBe('false')

  await userEvent.click(text)
  expect(useUiStore.getState().browseView).toBe('text')
  expect(text.getAttribute('aria-checked')).toBe('true')

  await userEvent.click(query)
  expect(useUiStore.getState().browseView).toBe('query')

  await userEvent.click(graph)
  expect(useUiStore.getState().browseView).toBe('graph')
})

it('adds the validate view as the fourth browse mode', async () => {
  shell('/browse/oid-1')
  const validate = screen.getByRole('radio', { name: /校验/ })
  expect(validate.getAttribute('aria-checked')).toBe('false')

  await userEvent.click(validate)
  expect(useUiStore.getState().browseView).toBe('validate')
  expect(validate.getAttribute('aria-checked')).toBe('true')
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

it('File▸Export offers R2RML download; 404 toasts the guide copy', async () => {
  // The api module is mocked at file level, so the 404 path is driven by
  // rejecting downloadBinary with the mocked ApiErr carrying the code —
  // the real fetch stub never reaches this component in this file.
  const toastErrorSpy = (await import('sonner')).toast.error as unknown as
    ReturnType<typeof vi.fn>
  vi.mocked(api.downloadBinary).mockRejectedValueOnce(
    // Full 4-arg ctor (tsc checks against the real module types; the mocked
    // class is a bare Error subclass, so code rides in via Object.assign).
    Object.assign(new ApiErr('NOT_FOUND', 'No R2RML mapping', null, 'r'), {
      code: 'NOT_FOUND',
    }),
  )
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
  await userEvent.hover(await screen.findByText('导出'))
  await userEvent.click(await screen.findByText('R2RML (.ttl)'))

  await waitFor(() =>
    expect(toastErrorSpy).toHaveBeenCalledWith('该本体没有 R2RML 映射——来自数据库起草的本体才有'),
  )
})
