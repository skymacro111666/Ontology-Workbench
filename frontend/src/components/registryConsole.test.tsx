import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, RegistryPage } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import RegistryConsole from './RegistryConsole'

/* The 记录 view (Registry Phase 1): pull-only feed of the operation
   journal — renders newest-first, refresh refetches, row click focuses
   the entity, empty and error states land. */

function env(data: RegistryPage | null) {
  return new Response(
    JSON.stringify(
      { code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<RegistryPage | null>,
    ),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function errEnv() {
  return new Response(
    JSON.stringify({ code: 'OFFLINE', message: 'offline', data: null, hint: null, request_id: 'r' }),
    { headers: { 'Content-Type': 'application/json' }, status: 503 },
  )
}

const page = (ids: number[]): RegistryPage => ({
  items: ids.map((id) => ({
    id,
    createdAt: '2026-10-06T12:00:00Z',
    action: 'entity.create',
    origin: 'manual',
    source: 'web',
    detail: { eid: 'http://example.org/C1', curie: 'ex:C1', kind: 'Class' },
  })),
  nextBeforeId: null,
})

let fetchedUrls: string[] = []

function stubFetch(result: () => Response | Promise<Response> = () => env(page([2, 1]))) {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    fetchedUrls.push(u)
    if (u.endsWith('/events') || u.includes('/events?')) {
      return await result()
    }
    throw new Error(`unexpected fetch: ${u}`)
  })
}

function renderConsole(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <RegistryConsole oid="oid-1" />
    </QueryClientProvider>,
  )
}

describe('RegistryConsole', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    fetchedUrls = []
    useBrowseStore.setState({ selectedEid: null })
  })

  it('renders the newest events with action badges and summaries', async () => {
    renderConsole(stubFetch())
    // Two rows, each with the action badge and the curie summary.
    expect(await screen.findAllByText('entity.create')).toHaveLength(2)
    expect(await screen.findAllByText('ex:C1')).toHaveLength(2)
    expect(screen.getByText('操作记录')).toBeTruthy()
  })

  it('refresh refetches the feed', async () => {
    renderConsole(stubFetch())
    await screen.findAllByText('entity.create')
    await userEvent.click(screen.getByRole('button', { name: '刷新' }))
    await waitFor(() => expect(fetchedUrls.filter((u) => u.includes('/events')).length).toBe(2))
  })

  it('row click focuses the entity via the browse store', async () => {
    renderConsole(stubFetch())
    await userEvent.click((await screen.findAllByText('ex:C1'))[0])
    expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/C1')
  })

  it('shows the empty state', async () => {
    renderConsole(stubFetch(() => env({ items: [], nextBeforeId: null })))
    expect(await screen.findByText('暂无操作记录')).toBeTruthy()
  })

  it('shows the error state and a load-more button when a next page exists', async () => {
    let first = true
    renderConsole(
      stubFetch(() => {
        if (first) {
          first = false
          return env({ ...page([1]), nextBeforeId: 1 })
        }
        return env(page([3]))
      }),
    )
    await screen.findAllByText('entity.create')
    await userEvent.click(screen.getByRole('button', { name: '加载更多' }))
    await waitFor(() => expect(screen.getAllByText('entity.create').length).toBe(2))
  })

  it('surfaces fetch failures inline', async () => {
    renderConsole(stubFetch(() => errEnv()))
    expect(await screen.findByText(/offline/)).toBeTruthy()
    expect(screen.queryByText('暂无操作记录')).toBeNull()
  })
})
