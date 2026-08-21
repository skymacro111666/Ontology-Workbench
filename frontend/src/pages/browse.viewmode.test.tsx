import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import Browse from './Browse'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, EntityIR, NodesEdges, OntologyMeta } from '../api/types'

const EID = 'http://example.org/Dog'

function meta(): OntologyMeta {
  return {
    id: 'oid-1',
    title: 'Pizza',
    filename: 'pizza.ttl',
    format: 'turtle',
    classCount: 99,
    propertyCount: 8,
    axiomCount: 300,
    fileSizeBytes: 106000,
    createdAt: '2026-08-21T00:00:00',
    fileHash: 'h',
    prefixes: { pizza: 'http://example.org/' },
  }
}

function entity(): EntityIR {
  return {
    eid: EID,
    curie: 'pizza:Dog',
    type: 'Class',
    label: { en: 'Dog' },
    comment: null,
    deprecated: false,
    parents: [{ eid: 'http://example.org/Animal', curie: 'pizza:Animal', label: {} }],
    children: [],
    properties: [],
    referencedBy: [],
    axioms: [{ turtle: 'x' }],
    stats: { directChildren: 2, totalDescendants: 2 },
  }
}

function neighbors(): NodesEdges {
  return {
    nodes: [
      { id: EID, curie: 'pizza:Dog', label: {}, kind: 'self' },
      { id: 'http://example.org/Animal', curie: 'pizza:Animal', label: {}, kind: 'class' },
    ],
    edges: [
      { source: EID, target: 'http://example.org/Animal', kind: 'subClassOf' },
    ],
  }
}

function stubFetch() {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    let data: unknown
    if (u.includes('/tree')) data = []
    else if (u.includes('/neighbors')) data = neighbors()
    else if (u.includes('/raw/')) data = { turtle: 'pizza:Dog a owl:Class .', eid: EID }
    else if (u.includes('/entities/')) data = entity()
    else data = meta()
    return new Response(
      JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
      { headers: { 'Content-Type': 'application/json' } },
    )
  })
}

function renderBrowse(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/browse/oid-1']}>
        {/* Route params only resolve through a Routes declaration. */}
        <Routes>
          <Route path="/browse/:oid" element={<Browse />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: EID, viewMode: 'detail', revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Browse view modes', () => {
  it('renders the mode switcher with detail active by default', async () => {
    renderBrowse(stubFetch())
    // Breadcrumb lineage <a>, breadcrumb current <strong>, and the detail
    // title all carry the curie — the lineage node lands a query round later.
    await waitFor(() =>
      expect(screen.getAllByText('pizza:Dog').length).toBeGreaterThanOrEqual(3),
    )
    expect(document.querySelector('.ant-segmented-item-selected')).toBeTruthy()
    expect(screen.getByRole('tab', { name: '概览' })).toBeTruthy()
  })

  it('switches to graph mode: neighbor canvas replaces the detail pane', async () => {
    const fetchMock = stubFetch()
    renderBrowse(fetchMock)
    await screen.findAllByText('pizza:Dog')
    await userEvent.click(screen.getByText('图'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/ontologies/oid-1/entities/${encodeURIComponent(EID)}/neighbors`,
        expect.anything(),
      ),
    )
    expect(await screen.findByText('pizza:Animal')).toBeTruthy() // neighbor node
    expect(screen.getByText('在总览中查看')).toBeTruthy()
    expect(screen.queryByRole('tab', { name: '概览' })).toBeNull() // detail pane gone
  })

  it('split mode shows canvas and detail side by side', async () => {
    renderBrowse(stubFetch())
    await screen.findAllByText('pizza:Dog')
    await userEvent.click(screen.getByText('分屏'))
    expect(await screen.findByText('pizza:Animal')).toBeTruthy() // graph side
    expect(screen.getByRole('tab', { name: '概览' })).toBeTruthy() // detail side
  })
})
