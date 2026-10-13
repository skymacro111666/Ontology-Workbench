import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import R2rmlEditor from './R2rmlEditor'
import { useUiStore } from '../stores/uiStore'

const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })
const err = (code: string, message: string, hint: string | null) =>
  new Response(
    JSON.stringify({ code, message, data: null, hint, request_id: 'r' }),
    { status: 422, headers: { 'Content-Type': 'application/json' } },
  )

const DOC = {
  filename: 'shop.r2rml.ttl',
  baseRevision: 0,
  schemaHash: 'h',
  createdAt: '2026-10-13T00:00:00Z',
  skippedTables: [],
  content: '@prefix rr: <http://www.w3.org/ns/r2rml#> .\n',
  contentHash: 'hash-1',
  previousExists: false,
  structure: [],
}

function renderEditor(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <R2rmlEditor oid="oid-1" doc={DOC} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.getState().setR2rmlDirty(false)
})

describe('R2rmlEditor', () => {
  it('disables save while clean, enables after an edit', async () => {
    /** 无 diff 时保存禁用;编辑后亮起并标脏 uiStore。 */
    const { container } = renderEditor(vi.fn(async () => ok(DOC)))
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    expect(screen.getByRole('button', { name: '保存' }).getAttribute('disabled')).not.toBeNull()
    await userEvent.click(content)
    await userEvent.keyboard('x')
    expect(screen.getByRole('button', { name: '保存' }).getAttribute('disabled')).toBeNull()
    expect(useUiStore.getState().r2rmlDirty).toBe(true)
  })

  it('saves via PUT with content+baseHash, then clears dirt', async () => {
    /** 保存走 PUT {content, baseHash};成功后脏标记清零、缓存失效重取。 */
    let putBody: { content: string; baseHash: string } | undefined
    let saved = ''
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { content: string; baseHash: string }
        putBody = body
        saved = body.content
        return ok({ ...DOC, content: saved, contentHash: 'hash-2', previousExists: true })
      }
      // GET reflects the server state (the saved text after a PUT).
      return ok({ ...DOC, content: saved || DOC.content, contentHash: saved ? 'hash-2' : DOC.contentHash })
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    vi.stubGlobal('fetch', fetchMock)
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <R2rmlEditor oid="oid-1" doc={DOC} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    await userEvent.click(content)
    document.getSelection()?.selectAllChildren(content)
    document.getSelection()?.collapseToEnd()
    await userEvent.keyboard('x')

    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(putBody?.baseHash).toBe('hash-1'))
    expect(putBody?.content.endsWith('x')).toBe(true)
    await waitFor(() => expect(useUiStore.getState().r2rmlDirty).toBe(false))
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalled()) // page-level refetch rides this
  })

  it('renders 422 findings as an inline panel and keeps the edits', async () => {
    /** 422 R2RML_INVALID:hint 按行渲染进错误面板,编辑内容不丢。 */
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'PUT')
        return err('R2RML_INVALID', 'R2RML 映射未通过校验(1 处)', 'L3: 列 customer.nme 不存在;可用:id、name')
      return ok(DOC)
    })
    const { container } = renderEditor(fetchMock)
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    await userEvent.click(content)
    await userEvent.keyboard('x')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText(/可用:id、name/)).toBeTruthy()
    expect(useUiStore.getState().r2rmlDirty).toBe(true) // 编辑保留
  })
})

describe('R2rmlEditor rollback', () => {
  it('rolls back to the previous version after confirmation', async () => {
    /** previousExists 时回退可点;确认后 POST rollback 带 baseHash,脏标记清零。 */
    let postBody: { baseHash: string } | undefined
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        postBody = JSON.parse(String(init.body)) as { baseHash: string }
        return ok({ ...DOC, content: 'old text', contentHash: 'hash-0', previousExists: false })
      }
      return ok({ ...DOC, previousExists: true })
    })
    vi.stubGlobal('fetch', fetchMock)
    // The editor takes the doc as a prop (the page owns the query): render
    // it directly with a previous version present.
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <R2rmlEditor oid="oid-1" doc={{ ...DOC, previousExists: true }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    await userEvent.click(screen.getByRole('button', { name: '回退上一版' }))
    await userEvent.click(await screen.findByRole('button', { name: '确认回退' }))
    await waitFor(() => expect(postBody?.baseHash).toBe('hash-1'))
    await waitFor(() => expect(useUiStore.getState().r2rmlDirty).toBe(false))
  })

  it('disables rollback without a previous version', async () => {
    /** 初版 previousExists=false:回退禁用。 */
    const { container } = renderEditor(vi.fn(async () => ok(DOC)))
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    expect(
      screen.getByRole('button', { name: '回退上一版' }).getAttribute('disabled'),
    ).not.toBeNull()
  })

  it('warns dirty edits are lost when rolling back', async () => {
    /** dirty 回退:确认框换文案,明示未保存修改将丢失(而非谎称可找回)。 */
    const { container } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <R2rmlEditor oid="oid-1" doc={{ ...DOC, previousExists: true }} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    await userEvent.click(content)
    await userEvent.keyboard('x')
    await userEvent.click(screen.getByRole('button', { name: '回退上一版' }))
    expect(await screen.findByText(/未保存的修改将丢失/)).toBeTruthy()
  })

  it('offers find/replace via the toolbar search button', async () => {
    /** 工具栏「搜索」按钮打开 CM6 官方面板(与文本页同引擎),输入即命中。 */
    const { container } = renderEditor(vi.fn(async () => ok(DOC)))
    const content = container.querySelector('.cm-content') as HTMLElement
    await waitFor(() => expect(content.getAttribute('contenteditable')).toBeTruthy())
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))
    const panel = container.querySelector('.cm-panel.cm-search')
    expect(panel).not.toBeNull()
    const find = panel?.querySelector('input[name="search"]') as HTMLInputElement
    await userEvent.type(find, 'rr')
    await waitFor(
      () => expect(container.querySelectorAll('.cm-searchMatch').length).toBeGreaterThanOrEqual(1),
      { timeout: 4000 },
    )
  })
})
