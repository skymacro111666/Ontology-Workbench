import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, NodesEdges } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
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

function renderGraph(fetchMock: (...args: unknown[]) => Promise<Response>, entry = '/graph/oid-1') {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      {/* GraphView resolves its color mode through the provider (carried T9 fix). */}
      <ThemeProvider>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/graph/:oid" element={<Graph />} />
            <Route path="/browse/:oid" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  lastLocation = ''
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Graph overview page', () => {
  it('shows the degradation notice only when truncated', async () => {
    renderGraph(vi.fn(async () => envelope(overview(true))))
    const notice = await screen.findByRole('status')
    expect(notice.textContent).toBe('本体超过 500 实体，仅显示顶层 3 层（共 800）')
    expect(screen.getByRole('heading', { name: '总览图' })).toBeTruthy()
  })

  it('renders no notice for small ontologies', async () => {
    renderGraph(vi.fn(async () => envelope(overview(false))))
    await screen.findByText('ex:Thing')
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('NOT_FOUND lands on the missing-ontology card with a way home', async () => {
    renderGraph(vi.fn(async () => envelope(null, 'NOT_FOUND')))
    expect(await screen.findByText('本体不存在')).toBeTruthy()
    expect(screen.getByText('它可能已被删除，或不属于当前用户。')).toBeTruthy()
    expect(screen.getByRole('link', { name: '返回首页' }).getAttribute('href')).toBe('/')
  })

  it('network failure shows loading, then the retry card; retry recovers', async () => {
    const fetchMock = vi
      .fn<(...args: unknown[]) => Promise<Response>>()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockImplementationOnce(async () => envelope(overview(false)))
    renderGraph(fetchMock)
    expect(screen.getByText('加载中…')).toBeTruthy()
    expect(await screen.findByText('加载失败')).toBeTruthy()
    expect(screen.getByText('无法连接服务器，请确认后端已启动。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('ex:Thing')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('navigates to browse with the eid query on node click, and offers a back link', async () => {
    renderGraph(vi.fn(async () => envelope(overview(false))))
    await screen.findByText('ex:Dog')
    // Back button targets the workbench (checked before navigating away).
    expect(screen.getByRole('link', { name: '返回工作区' }).getAttribute('href')).toBe('/browse/oid-1')
    // fireEvent: userEvent's pointer sequence trips React Flow's d3-drag in jsdom.
    fireEvent.click(screen.getByText('ex:Dog'))
    await waitFor(() =>
      expect(lastLocation).toBe(`/browse/oid-1?eid=${encodeURIComponent('http://example.org/Dog')}`),
    )
  })

  it('focus param highlights the focused node', async () => {
    renderGraph(
      vi.fn(async () => envelope(overview(false))),
      `/graph/oid-1?focus=${encodeURIComponent('http://example.org/Dog')}`,
    )
    const dog = await screen.findByText('ex:Dog')
    // Focused node is ringed with the primary token classes (Tailwind).
    await waitFor(() => expect(dog.className).toContain('border-primary'))
  })
})
