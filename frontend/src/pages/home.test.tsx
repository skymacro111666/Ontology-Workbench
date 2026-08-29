import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import Home from './Home'
import { LAST_OID_KEY } from '../auth/AuthContext'
import { useUiStore } from '../stores/uiStore'
import type { OntologySummary } from '../api/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
  useUiStore.getState().setImportOpen(false)
})

/** Envelope helpers matching the API contract (code/message/data/hint/request_id). */
const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

/** OntologySummary factory; per-test overrides keep fixtures readable. */
function summary(id: string, over: Partial<OntologySummary> = {}): OntologySummary {
  return {
    id,
    title: id,
    filename: `${id}.ttl`,
    format: 'turtle',
    classCount: 0,
    propertyCount: 0,
    axiomCount: 0,
    instanceCount: 0,
    fileSizeBytes: 1024,
    createdAt: '2026-08-21T00:00:00',
    ...over,
  }
}

/** Marks /browse/:id navigations so open flows are assertable. */
function BrowseRoute() {
  const { id } = useParams()
  return <p>browse:{id}</p>
}

function renderHome() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/browse/:id" element={<BrowseRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const deleteCalls = (fetchMock: Mock) =>
  fetchMock.mock.calls.filter(
    ([url, init]) => String(url).includes('/api/ontologies/') && init?.method === 'DELETE',
  )

describe('Home', () => {
  it('renders stat tiles with the aggregated counts', async () => {
    // 17+25 classes, 4+9 properties, 52+148 axioms.
    const fetchMock = vi.fn(async () =>
      ok({
        items: [
          summary('a', { classCount: 17, propertyCount: 4, axiomCount: 52, fileSizeBytes: 106000 }),
          summary('b', { classCount: 25, propertyCount: 9, axiomCount: 148, fileSizeBytes: 20480 }),
        ],
        total: 2,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderHome()

    // A data-dependent count pill proves the query resolved before tile values.
    expect(await screen.findByText('17 类')).toBeTruthy()
    expect(screen.getByText('4 属性')).toBeTruthy()
    expect(screen.getByText('52 公理')).toBeTruthy()
    expect(screen.getByText('本体')).toBeTruthy()
    expect(screen.getByText('2')).toBeTruthy()
    expect(screen.getByText('类')).toBeTruthy()
    expect(screen.getByText('42')).toBeTruthy()
    expect(screen.getByText('属性')).toBeTruthy()
    expect(screen.getByText('13')).toBeTruthy()
    expect(screen.getByText('公理')).toBeTruthy()
    expect(screen.getByText('200')).toBeTruthy()
    // Spec: tile numbers use tabular figures so columns of digits align.
    expect(screen.getByText('200').className).toContain('tabular-nums')
  })

  // The inline sample cards were removed from the page (user direction);
  // the empty-state "载入示例" entry keeps the same POST /samples flow.

  it('deletes only after the AlertDialog confirmation', async () => {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (String(url) === '/api/ontologies/oid-1' && init?.method === 'DELETE') return ok(null)
      return ok({ items: [summary('oid-1', { title: 'Pizza' })], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderHome()

    await userEvent.click(await screen.findByRole('button', { name: '删除 Pizza' }))
    expect(await screen.findByRole('alertdialog')).toBeTruthy()
    expect(screen.getByText('删除「Pizza」？')).toBeTruthy()
    // Confirmation gate: no DELETE until the dialog's action is clicked.
    expect(deleteCalls(fetchMock)).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => expect(deleteCalls(fetchMock)).toHaveLength(1))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ontologies/oid-1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('keeps the confirm dialog open with its action disabled while deleting', async () => {
    // In-flight feedback (backlog T6①②): the dialog itself is the busy state —
    // it must not vanish on the first click leaving only a toast as feedback.
    let resolveDelete!: (v: Response) => void
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (String(url) === '/api/ontologies/oid-1' && init?.method === 'DELETE') {
        return new Promise<Response>((r) => {
          resolveDelete = r
        })
      }
      return ok({ items: [summary('oid-1', { title: 'Pizza' })], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderHome()

    await userEvent.click(await screen.findByRole('button', { name: '删除 Pizza' }))
    await userEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => expect(deleteCalls(fetchMock)).toHaveLength(1))

    // The dialog is still up as the in-flight feedback; the action is
    // disabled and relabeled so no second click can race the first.
    const action = screen.getByRole('button', { name: '删除中…' }) as HTMLButtonElement
    expect(action.disabled).toBe(true)
    expect(screen.getByRole('alertdialog')).toBeTruthy()

    await act(async () => {
      resolveDelete(ok(null))
    })
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  })

  it('shows the empty state with both onboarding buttons wired', async () => {
    const fetchMock = vi.fn(async (url: string | URL) => {
      if (String(url) === '/api/samples/pizza') return ok(summary('oid-pizza'))
      return ok({ items: [], total: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderHome()

    expect(await screen.findByText('还没有本体')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '导入本体' }))
    expect(useUiStore.getState().importOpen).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: '载入示例 pizza' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/samples/pizza',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })

  it('opens a list card: writes LAST_OID_KEY and navigates to /browse/:id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ok({ items: [summary('oid-1', { title: 'Pizza' })], total: 1 })),
    )
    renderHome()

    await userEvent.click(await screen.findByRole('button', { name: '打开' }))
    expect(localStorage.getItem(LAST_OID_KEY)).toBe('oid-1')
    expect(await screen.findByText('browse:oid-1')).toBeTruthy()
  })

  it('shows an error state with retry when the list fails to load', async () => {
    // Non-JSON body (e.g. a proxy error page): transport-level, not an ApiErr.
    vi.stubGlobal('fetch', vi.fn(async () => new Response('bad gateway', { status: 502 })))
    renderHome()
    expect(await screen.findByText('列表加载失败')).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  })
})
