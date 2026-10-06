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

  it('shows field-level from→to changes inline, pipe-separated, all fields', async () => {
    renderConsole(
      stubFetch(() =>
        env({
          items: [
            {
              id: 1,
              createdAt: '2026-10-06T12:00:00Z',
              action: 'entity.update',
              origin: 'manual',
              source: 'web',
              detail: {
                eid: 'http://example.org/Payment',
                curie: 'ex:Payment',
                changes: {
                  label: { from: { '': 'Payment' }, to: { '': 'Zahlung' } },
                  comment: { from: null, to: 'net' },
                  parents: { from: ['http://example.org/A'], to: ['http://example.org/B'] },
                  ranges: { from: [], to: ['http://example.org/C'] },
                },
              },
            },
          ],
          nextBeforeId: null,
        }),
      ),
    )
    // Inline on the row (same line as the curie), pipe-separated, and NO
    // three-field cap — the fourth change must survive; long content wraps.
    expect(
      await screen.findByText(/label: Payment → Zahlung \| comment: ∅ → net/),
    ).toBeTruthy()
    expect(screen.getByText(/ranges: \[\] → http:\/\/example.org\/C/)).toBeTruthy()
  })

  it('surfaces fetch failures inline', async () => {
    renderConsole(stubFetch(() => errEnv()))
    expect(await screen.findByText(/offline/)).toBeTruthy()
    expect(screen.queryByText('暂无操作记录')).toBeNull()
  })

  it('drops loaded pages when the oid switches (no cross-ontology residue)', async () => {
    // oid-1's feed pages carry ex:C*, oid-2's carries ex:D9; the mock
    // routes by URL so the switch itself exercises the real query path.
    const pageOf = (curie: string, ids: number[], next: number | null) => ({
      items: ids.map((id) => ({
        id,
        createdAt: '2026-10-06T12:00:00Z',
        action: 'entity.create',
        origin: 'manual',
        source: 'web',
        detail: { eid: `http://example.org/${curie}`, curie: `ex:${curie}` },
      })),
      nextBeforeId: next,
    })
    const mock = vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.includes('oid-2')) return env(pageOf('D9', [9], null))
      if (u.includes('before_id')) return env(pageOf('C2', [2], null))
      return env(pageOf('C1', [1], 1))
    })
    vi.stubGlobal('fetch', mock)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const tree = (o: string) => (
      <QueryClientProvider client={qc}>
        <RegistryConsole oid={o} />
      </QueryClientProvider>
    )
    const { rerender } = render(tree('oid-1'))
    expect(await screen.findAllByText('ex:C1')).toBeTruthy()
    // Pull one older page so local pagination state is non-empty…
    await userEvent.click(screen.getByRole('button', { name: '加载更多' }))
    expect(await screen.findAllByText('ex:C2')).toBeTruthy()
    // …then switch ontologies on the same route: nothing of oid-1 survives.
    rerender(tree('oid-2'))
    expect(await screen.findAllByText('ex:D9')).toBeTruthy()
    expect(screen.queryByText('ex:C2')).toBeNull()
    expect(screen.queryByText('ex:C1')).toBeNull()
  })
})
