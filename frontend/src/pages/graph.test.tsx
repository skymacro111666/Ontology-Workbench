import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, NodesEdges, OntologyMeta } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
import { useBrowseStore } from '../stores/browseStore'
import Browse from './Browse'
import Graph from './Graph'

function overview(truncated: boolean): NodesEdges {
  return {
    nodes: [
      { id: 'http://example.org/Thing', curie: 'ex:Thing', label: {}, kind: 'class' },
      { id: 'http://example.org/Dog', curie: 'ex:Dog', label: {}, kind: 'class' },
    ],
    edges: [{ source: 'http://example.org/Dog', target: 'http://example.org/Thing', kind: 'subClassOf' }],
    truncated,
    totalCount: truncated ? 800 : 2,
  }
}

function meta(): OntologyMeta {
  return {
    id: 'oid-1',
    title: 'Ex',
    filename: 'ex.ttl',
    format: 'turtle',
    classCount: 2,
    propertyCount: 0,
    axiomCount: 4,
    fileSizeBytes: 100,
    createdAt: '2026-08-21T00:00:00',
    fileHash: 'h',
    prefixes: {},
  }
}

function envelope(payload: unknown, code = 'OK') {
  return new Response(
    JSON.stringify({
      code, message: 'ok', data: payload, hint: null, request_id: 'r',
    } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

let lastLocation = ''

/** Records where navigation lands; mounted at the /browse route. */
function LocationProbe() {
  const location = useLocation()
  useEffect(() => {
    lastLocation = location.pathname + location.search
  }, [location])
  return null
}

/** Fetch stub routing by URL: meta/tree/overview; overview failures injectable. */
function fetchFor(ov: NodesEdges, overviewFail?: Error) {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    if (u.includes('/overview')) {
      if (overviewFail) throw overviewFail
      return envelope(ov)
    }
    if (u.includes('/meta')) return envelope(meta())
    if (u.includes('/tree')) return envelope([])
    return envelope(null)
  })
}

/** Workspace in overview mode: Browse driven by the store's view mode. */
function renderOverview(
  fetchMock: (url: string | URL) => Promise<Response>,
  entry = '/browse/oid-1',
) {
  useBrowseStore.setState({ selectedEid: null })
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      {/* GraphView resolves its color mode through the provider (carried T9 fix). */}
      <ThemeProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/browse/:oid" element={<Browse />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

describe('workspace overview mode', () => {
  it('shows the degradation notice only when truncated', async () => {
    renderOverview(fetchFor(overview(true)))
    const notice = await screen.findByRole('status')
    expect(notice.textContent).toBe('本体超过 500 实体，仅显示顶层 3 层（共 800）')
  })

  it('renders no notice for small ontologies', async () => {
    renderOverview(fetchFor(overview(false)))
    await screen.findByText('ex:Thing')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('NOT_FOUND lands on the missing-ontology card with a way home', async () => {
    renderOverview(vi.fn(async () => envelope(null, 'NOT_FOUND')))
    expect(await screen.findByText('本体不存在')).toBeTruthy()
    expect(screen.getByText('它可能已被删除，或不属于当前用户。')).toBeTruthy()
    expect(screen.getByRole('link', { name: '返回首页' }).getAttribute('href')).toBe('/')
  })

  it('overview failure shows the retry card; retry recovers', async () => {
    let fail = true
    const fetchMock = vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.includes('/overview') && fail) {
        fail = false // only the first overview call fails; the retry recovers
        throw new TypeError('Failed to fetch')
      }
      if (u.includes('/overview')) return envelope(overview(false))
      if (u.includes('/meta')) return envelope(meta())
      if (u.includes('/tree')) return envelope([])
      return envelope(null)
    })
    renderOverview(fetchMock)
    expect(await screen.findByText('加载失败')).toBeTruthy()
    expect(screen.getByText('无法连接服务器，请确认后端已启动。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('ex:Thing')).toBeTruthy()
  })

  it('node click selects the entity in the workspace (reveal wiring)', async () => {
    renderOverview(fetchFor(overview(false)))
    await screen.findByText('ex:Dog')
    // fireEvent: userEvent's pointer sequence trips React Flow's d3-drag in jsdom.
    fireEvent.click(screen.getByText('ex:Dog'))
    await waitFor(() =>
      expect(useBrowseStore.getState().selectedEid).toBe('http://example.org/Dog'),
    )
  })

  it('focused entity deep link highlights the node', async () => {
    renderOverview(
      fetchFor(overview(false)),
      `/browse/oid-1?view=overview&focus=${encodeURIComponent('http://example.org/Dog')}`,
    )
    const dog = await screen.findByText('ex:Dog')
    // Highlighted = 2px primary border, bold primary text, star (mockup).
    await waitFor(() => expect(dog.className).toContain('border-primary'))
    expect(dog.textContent).toContain('★')
  })
})

describe('legacy /graph route', () => {
  it('redirects into the workspace overview mode, focus preserved', async () => {
    vi.stubGlobal('fetch', fetchFor(overview(false)))
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <MemoryRouter
            initialEntries={[`/graph/oid-1?focus=${encodeURIComponent('http://example.org/Dog')}`]}
          >
            <Routes>
              <Route path="/graph/:oid" element={<Graph />} />
              <Route path="/browse/:oid" element={<LocationProbe />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(lastLocation).toBe(
        `/browse/oid-1?view=overview&focus=${encodeURIComponent('http://example.org/Dog')}`,
      ),
    )
  })
})
