import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Browse from './Browse'
import { useBrowseStore } from '../stores/browseStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import type { Envelope, EntityIR, NodesEdges, OntologyMeta } from '../api/types'

const EID = 'http://example.org/Dog'
const ANIMAL = 'http://example.org/Animal'

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
    parseMs: 1200,
  }
}

/** Dog: one parent (Animal). Animal: root class, no parents. */
function dog(): EntityIR {
  return {
    eid: EID,
    curie: 'pizza:Dog',
    type: 'Class',
    label: { en: 'Dog' },
    comment: null,
    deprecated: false,
    parents: [{ eid: ANIMAL, curie: 'pizza:Animal', label: {} }],
    children: [],
    properties: [],
    referencedBy: [],
    axioms: [{ turtle: 'x' }],
    stats: { directChildren: 2, totalDescendants: 2 },
  }
}

function animal(): EntityIR {
  return { ...dog(), eid: ANIMAL, curie: 'pizza:Animal', parents: [] }
}

function overview(): NodesEdges {
  return {
    nodes: [
      { id: EID, curie: 'pizza:Dog', label: {}, kind: 'class' },
      { id: ANIMAL, curie: 'pizza:Animal', label: {}, kind: 'class' },
    ],
    edges: [{ source: EID, target: ANIMAL, kind: 'subClassOf' }],
  }
}

function stubFetch() {
  return vi.fn(async (url: string | URL) => {
    const u = String(url)
    let data: unknown
    if (u.includes('/overview')) data = overview()
    else if (u.includes('/tree')) data = []
    else if (u.includes(encodeURIComponent(ANIMAL))) data = animal()
    else if (u.includes('/entities/')) data = dog()
    else data = meta()
    return new Response(
      JSON.stringify({
        code: 'OK',
        message: 'ok',
        data,
        hint: null,
        request_id: 'r',
      } satisfies Envelope<unknown>),
      { headers: { 'Content-Type': 'application/json' } },
    )
  })
}

function renderBrowse(
  fetchMock: ReturnType<typeof stubFetch>,
  { entry = '/browse/oid-1' }: { entry?: string } = {},
) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    fetchMock,
    ...render(
      <QueryClientProvider client={qc}>
        {/* GraphView reads the resolved color mode through the provider. */}
        <ThemeProvider>
          <MemoryRouter initialEntries={[entry]}>
            {/* Route params only resolve through a Routes declaration. */}
            <Routes>
              <Route path="/browse/:oid" element={<Browse />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Browse workspace (overview-only)', () => {
  it('renders all four zones: tree tabs, canvas, resident inspector, statusbar', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    renderBrowse(stubFetch())
    expect(await screen.findAllByText('pizza:Dog')).toBeTruthy()

    // Zone 1: class-tree pill tabs.
    expect(screen.getByRole('button', { name: '类' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '命名空间' })).toBeTruthy()
    // Zone 2: whole-ontology canvas nodes (Animal also chips in the inspector).
    expect(screen.getAllByText('pizza:Animal').length).toBeGreaterThanOrEqual(1)
    // Zone 3: resident inspector shows the selected entity's URI block.
    expect(screen.getByText(EID).closest('pre')).toBeTruthy()
    // Label badge: "value lang" pill (mockup §7.2).
    expect(screen.getAllByText('Dog en').length).toBeGreaterThanOrEqual(1)
    // Zone 4: statusbar copy (mono filename · counts · green parse status).
    expect(screen.getByText('pizza.ttl')).toBeTruthy()
    expect(screen.getByText('99 类')).toBeTruthy()
    expect(screen.getByText('解析 OK · 1.2s')).toBeTruthy()
  })

  it('canvas node click selects through reveal and walks the tree', async () => {
    renderBrowse(stubFetch())
    expect(await screen.findByText('pizza:Animal')).toBeTruthy()

    // fireEvent: userEvent's pointer sequence trips React Flow's d3-drag in jsdom.
    fireEvent.click(screen.getByText('pizza:Animal'))

    // Selection lands in the store; tree walk + inspector follow it (the
    // reveal→fetch chain is covered end-to-end in graph.test).
    await waitFor(() => expect(useBrowseStore.getState().selectedEid).toBe(ANIMAL))
  })

  it('no selection: inspector empty state, statusbar still shows', async () => {
    renderBrowse(stubFetch())
    expect(await screen.findByText('pizza.ttl')).toBeTruthy()
    expect(screen.getByText('在树或图中选择一个实体')).toBeTruthy()
  })

  it('deep link ?eid= selects the entity on entry', async () => {
    renderBrowse(stubFetch(), { entry: `/browse/oid-1?eid=${encodeURIComponent(EID)}` })
    expect(await screen.findByText(EID)).toBeTruthy()
    expect(useBrowseStore.getState().selectedEid).toBe(EID)
  })
})
