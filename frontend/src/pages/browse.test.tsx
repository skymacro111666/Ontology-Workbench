import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Browse from './Browse'
import { useBrowseStore } from '../stores/browseStore'
import { useRequestStore } from '../stores/requestStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import type { Envelope, EntityIR, NodesEdges, OntologyMeta } from '../api/types'

const EID = 'http://example.org/Dog'
const PROP = 'http://example.org/hasFur'
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
  return {
    ...dog(),
    eid: ANIMAL,
    curie: 'pizza:Animal',
    parents: [],
  }
}

function neighbors(): NodesEdges {
  return {
    nodes: [
      { id: EID, curie: 'pizza:Dog', label: {}, kind: 'self' },
      { id: ANIMAL, curie: 'pizza:Animal', label: {}, kind: 'class' },
      { id: PROP, curie: 'pizza:hasFur', label: {}, kind: 'property' },
    ],
    edges: [
      { source: EID, target: ANIMAL, kind: 'subClassOf' },
      { source: EID, target: PROP, kind: 'property' },
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
    else if (u.includes(encodeURIComponent(ANIMAL))) data = animal()
    else if (u.includes('/entities/')) data = dog()
    else data = meta()
    return new Response(
      JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
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

/** ToggleGroup items are radios (single type); view modes share one group. */
async function switchMode(name: '详情' | '分屏' | '图') {
  await userEvent.click(screen.getByRole('radio', { name }))
}

beforeEach(() => {
  useBrowseStore.setState({
    selectedEid: null,
    viewMode: 'detail',
    revealEid: null,
    ttlFocusEid: null,
    ttlNonce: 0,
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Browse four-zone workspace', () => {
  it('renders all four zones: tree tabs, toolbar, resident inspector, statusbar', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    renderBrowse(stubFetch())
    expect(await screen.findAllByText('pizza:Dog')).toBeTruthy()

    // Zone 1: class-tree tri-tabs.
    expect(screen.getByRole('tab', { name: '类' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '前缀' })).toBeTruthy()
    // Zone 4: statusbar copy (mono filename · counts · parse status).
    expect(screen.getByText('pizza.ttl')).toBeTruthy()
    expect(screen.getByText('99 类')).toBeTruthy()
    expect(screen.getByText('8 属性')).toBeTruthy()
    expect(screen.getByText('300 公理')).toBeTruthy()
    expect(screen.getByText('解析 OK')).toBeTruthy()
    // Parse duration from meta, formatted seconds over 1s (mockup §7.4).
    expect(screen.getByText('1.2s')).toBeTruthy()
    // Zone 3: resident inspector shows the selected entity's URI block.
    expect(screen.getByText(EID).closest('pre')).toBeTruthy()
    // Label badges: text first, muted language marker after (mockup §7.2).
    expect(screen.getAllByText('Dog').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('en').length).toBeGreaterThanOrEqual(1)
    // Detail is the default mode and full (TTL tab present, not compact).
    expect(screen.getByRole('radio', { name: '详情' }).getAttribute('data-state')).toBe('on')
    expect(screen.getByRole('tab', { name: '原始 TTL' })).toBeTruthy()
    // The overview jump appears twice — toolbar right and inspector action —
    // both targeting the selected entity.
    const overviewLinks = screen.getAllByRole('link', { name: '在总览中查看' })
    expect(overviewLinks.map((a) => a.getAttribute('href'))).toEqual(
      overviewLinks.map(() => `/graph/oid-1?focus=${encodeURIComponent(EID)}`),
    )
    // Statusbar right segment: last OK request from the client store,
    // method/path · duration · request_id prefix (mockup §7.4).
    useRequestStore.getState().set({
      method: 'GET',
      path: '/entities/Margherita',
      ms: 32,
      requestId: 'a3f9c2d1e2',
    })
    await waitFor(() => {
      expect(screen.getByText('GET /entities/Margherita')).toBeTruthy()
      expect(screen.getByText('32ms')).toBeTruthy()
      expect(screen.getByText('a3f9c2')).toBeTruthy()
    })
  })

  it('graph mode: toolbar carries edge-label switch and type filter over the canvas', async () => {
    useBrowseStore.setState({ selectedEid: EID, viewMode: 'graph' })
    renderBrowse(stubFetch())
    // Canvas settled with all three node kinds visible.
    expect(await screen.findByText('pizza:hasFur')).toBeTruthy()
    // Toolbar controls beside the mode switch (mockup §5.4); the in-canvas
    // overlay variant must be gone so the two cannot drift apart.
    expect(screen.getByRole('button', { name: '边标签' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: '全部类型' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '标签' })).toBeNull()
    // Classes-only filter drops the property node from the canvas.
    fireEvent.click(screen.getByRole('radio', { name: '仅类' }))
    await waitFor(() => expect(screen.queryByText('pizza:hasFur')).toBeNull())
    // Dog stays (breadcrumb + canvas node).
    expect(screen.getAllByText('pizza:Dog').length).toBeGreaterThanOrEqual(1)
  })

  it('graph mode: neighbors canvas full width, detail gone, inspector stays', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    const { fetchMock } = renderBrowse(stubFetch())
    await screen.findAllByText('pizza:Dog')
    await switchMode('图')
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/ontologies/oid-1/entities/${encodeURIComponent(EID)}/neighbors`,
        expect.anything(),
      ),
    )
    // Neighbor node on the canvas (the breadcrumb lineage repeats the curie).
    await screen.findAllByText('pizza:Animal')
    expect(screen.queryByRole('tab', { name: '概览' })).toBeNull() // detail pane gone
    // Inspector is resident across modes.
    expect(screen.getByText(EID).closest('pre')).toBeTruthy()
    // The self node is ring-highlighted (same visual as overview focus).
    await waitFor(() =>
      expect(
        screen.getAllByText('pizza:Dog').some((el) => el.classList.contains('border-primary')),
      ).toBe(true),
    )
  })

  it('split mode: canvas plus compact detail, and compact fetches no raw TTL', async () => {
    // Enter split directly so no full detail pane ever mounts.
    useBrowseStore.setState({ selectedEid: EID, viewMode: 'split' })
    const { fetchMock } = renderBrowse(stubFetch())
    // Canvas side and compact detail side render together.
    await screen.findAllByText('pizza:Animal')
    expect(screen.getByRole('tab', { name: '概览' })).toBeTruthy()
    expect(screen.queryByRole('tab', { name: '原始 TTL' })).toBeNull() // compact
    // Compact renders no TTL tab, so Browse never fetches raw TTL for it.
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/raw/'))).toBe(false)
  })

  it('deep link ?eid= selects the entity on entry', async () => {
    const { fetchMock } = renderBrowse(stubFetch(), {
      entry: `/browse/oid-1?eid=${encodeURIComponent(EID)}`,
    })
    expect(await screen.findAllByText('pizza:Dog')).toBeTruthy()
    expect(useBrowseStore.getState().selectedEid).toBe(EID)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/ontologies/oid-1/entities/${encodeURIComponent(EID)}`,
      expect.anything(),
    )
  })

  it('no selection: inspector empty state, no entity fetch, statusbar still shows', async () => {
    const { fetchMock } = renderBrowse(stubFetch())
    // Zones render once meta loads; the empty states arrive with them.
    expect(await screen.findByText('在树或图中选择一个实体')).toBeTruthy()
    expect(screen.getByText('选择左侧实体查看详情')).toBeTruthy()
    expect(await screen.findByText('pizza.ttl')).toBeTruthy()
    expect(
      fetchMock.mock.calls.every(([u]) => !String(u).includes('/entities/')),
    ).toBe(true)
  })

  it('canvas node click selects through reveal and walks the tree', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    const { fetchMock } = renderBrowse(stubFetch())
    await screen.findAllByText('pizza:Dog')
    await switchMode('图')
    // The flow node (not the breadcrumb button carrying the same curie).
    const node = (await screen.findAllByText('pizza:Animal')).find((el) =>
      el.closest('.react-flow__node'),
    )
    expect(node).toBeTruthy()
    // userEvent's pointer sequence trips React Flow's d3-drag mousedown
    // handler, which jsdom cannot serve (null event.view); a plain click
    // reaches React's onNodeClick without it.
    fireEvent.click(node as HTMLElement)
    expect(useBrowseStore.getState().selectedEid).toBe(ANIMAL)
    // reveal() also asks the class tree to materialize the ancestor path.
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/ontologies/oid-1/tree?parent=${encodeURIComponent(ANIMAL)}`,
        expect.anything(),
      ),
    )
  })

  it('breadcrumb lineage links reveal each ancestor level', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    renderBrowse(stubFetch())
    const nav = await screen.findByLabelText('类谱系')
    // Chain root › selected, the current entity emphasized at the end.
    expect(within(nav).getByText('pizza:Animal')).toBeTruthy()
    expect(within(nav).getByText('pizza:Dog').tagName).toBe('STRONG')
    await userEvent.click(within(nav).getByText('pizza:Animal'))
    expect(useBrowseStore.getState().selectedEid).toBe(ANIMAL)
  })

  it('inspector 原始 TTL action lands on detail mode with the TTL tab open', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    renderBrowse(stubFetch())
    await screen.findAllByText('pizza:Dog')
    await switchMode('分屏')
    // Split keeps the inspector button the only 原始 TTL control.
    await userEvent.click(screen.getByRole('button', { name: '原始 TTL' }))
    expect(useBrowseStore.getState().viewMode).toBe('detail')
    // The central detail reopens on its TTL tab (store signal consumed).
    expect((await screen.findByRole('tab', { name: '原始 TTL' })).getAttribute('aria-selected')).toBe(
      'true',
    )
    expect(await screen.findByText(/a owl:Class/)).toBeTruthy()
    // A repeated ask after manually returning to overview re-opens TTL.
    await userEvent.click(screen.getByRole('tab', { name: '概览' }))
    expect(screen.queryByText(/a owl:Class/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '原始 TTL' }))
    expect(await screen.findByText(/a owl:Class/)).toBeTruthy()
  })

  it('TTL ask then split keeps the compact pane on its overview', async () => {
    useBrowseStore.setState({ selectedEid: EID })
    renderBrowse(stubFetch())
    await screen.findAllByText('pizza:Dog')
    // Landed on detail with the TTL tab open; the signal stays set.
    await userEvent.click(screen.getByRole('button', { name: '原始 TTL' }))
    expect(await screen.findByText(/a owl:Class/)).toBeTruthy()
    await switchMode('分屏')
    // The compact pane mounts fresh while ttlFocusEid still targets the
    // entity: overview must win (compact has no TTL tab to select).
    const tab = screen.getByRole('tab', { name: '概览' })
    expect(tab.getAttribute('aria-selected')).toBe('true')
    const content = document.getElementById(tab.getAttribute('aria-controls') ?? '')
    expect(content?.getAttribute('data-state')).toBe('active')
    // Overview body (parents section) is actually mounted, not a blank pane.
    expect(content?.textContent).toContain('pizza:Animal')
  })
})
