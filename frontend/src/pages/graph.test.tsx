import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import Graph from './Graph'
import type { Envelope, NodesEdges } from '../api/types'

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

let lastLocation = ''

function probe() {
  return function LocationProbe() {
    lastLocation = useLocation().pathname + useLocation().search
    return null
  }
}

function renderGraph(fetchMock: ReturnType<typeof stubFetch>, entry = '/graph/oid-1') {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Probe = probe()
  return render(
    <QueryClientProvider client={qc}>
      {/* Same primary token as main.tsx so border-color assertions hold. */}
      <ConfigProvider theme={{ token: { colorPrimary: '#0D9488' } }}>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/graph/:oid" element={<Graph />} />
            <Route path="/browse/:oid" element={<Probe />} />
          </Routes>
        </MemoryRouter>
      </ConfigProvider>
    </QueryClientProvider>,
  )
}

function stubFetch(payload: NodesEdges) {
  return vi.fn(async () =>
    new Response(
      JSON.stringify({
        code: 'OK', message: 'ok', data: payload, hint: null, request_id: 'r',
      } satisfies Envelope<NodesEdges>),
      { headers: { 'Content-Type': 'application/json' } },
    ),
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
  it('shows the degradation alert only when truncated', async () => {
    renderGraph(stubFetch(overview(true)), '/graph/oid-1')
    expect(await screen.findByText(/仅显示顶层 3 层/)).toBeTruthy()
    expect(screen.getByText(/800/)).toBeTruthy()
  })

  it('renders no alert for small ontologies', async () => {
    renderGraph(stubFetch(overview(false)), '/graph/oid-1')
    await screen.findByText('ex:Thing')
    expect(screen.queryByText(/仅显示顶层 3 层/)).toBeNull()
  })

  it('navigates to browse with the eid query on node click, and offers a back button', async () => {
    renderGraph(stubFetch(overview(false)), '/graph/oid-1')
    await screen.findByText('ex:Dog')
    // Back button targets the workbench (checked before navigating away).
    expect(screen.getByRole('link', { name: /返回工作区/ })).toBeTruthy()
    // fireEvent: userEvent's pointer sequence trips React Flow's d3-drag in jsdom.
    fireEvent.click(screen.getByText('ex:Dog'))
    await waitFor(() =>
      expect(lastLocation).toBe(`/browse/oid-1?eid=${encodeURIComponent('http://example.org/Dog')}`),
    )
  })

  it('focus param highlights the focused node', async () => {
    renderGraph(
      stubFetch(overview(false)),
      `/graph/oid-1?focus=${encodeURIComponent('http://example.org/Dog')}`,
    )
    const dog = await screen.findByText('ex:Dog')
    // Focused node is highlighted with the primary border class (Tailwind token).
    await waitFor(() => expect(dog.className).toContain('border-primary'))
  })
})
