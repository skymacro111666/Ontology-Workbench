import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { Toaster } from './ui/sonner'
import type { Envelope, NodesEdges } from '../api/types'
import { useBrowseStore } from '../stores/browseStore'
import { useUiStore } from '../stores/uiStore'
import { ThemeProvider } from '../theme/ThemeProvider'
import { g6Instances, lastG6, resetG6 } from '../test/g6Mock'
import GraphOverview from './GraphOverview'

/* The overview owns the layout query: it waits for GET /layout before
   mounting the canvas, PUTs the debounced drag map, and the 重排 button
   DELETEs the row so the next mount returns to the auto pipeline. */

vi.mock('@antv/g6', async () => {
  const mock = await import('../test/g6Mock')
  return {
    Graph: mock.MockGraph,
    BaseLayout: mock.BaseLayout,
    register: mock.register,
    ExtensionCategory: mock.ExtensionCategory,
  }
})

const OVERVIEW: NodesEdges = {
  nodes: [{ id: 'a', curie: 'ex:A', label: {}, kind: 'class' }],
  edges: [],
  truncated: false,
  totalCount: 1,
}

/** Truncated variant: same canvas content, but flagged as cut off. */
const TRUNCATED_OVERVIEW: NodesEdges = { ...OVERVIEW, truncated: true }

function env(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

let savedBody: { positions: Record<string, { x: number; y: number }> } | undefined

function stubFetch(
  layout: Record<string, { x: number; y: number }> | null = null,
  overview: NodesEdges = OVERVIEW,
) {
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    if (u.includes('/overview')) return env(overview)
    if (u.endsWith('/layout') && init?.method === 'PUT') {
      savedBody = JSON.parse(String(init.body))
      return env(savedBody)
    }
    return env({ positions: layout ?? {} })
  })
}

function draw(fetchMock: ReturnType<typeof stubFetch>, focus?: string) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <Toaster />
        <GraphOverview oid="oid-1" focus={focus} />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  resetG6()
  savedBody = undefined
  useUiStore.setState({ entityDialog: null, instanceDialog: null })
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // Sonner keeps toasts in a module-global store that outlives unmounting;
  // drop them so a prior test's toast cannot leak into the next Toaster.
  toast.dismiss()
})

describe('GraphOverview layout persistence', () => {
  it('mounts the canvas with the auto pipeline when nothing is saved', async () => {
    draw(stubFetch())
    await waitForGraph()
    expect(Array.isArray(lastG6()!.options.layout)).toBe(true)
  })

  it('switches the canvas off the auto pipeline when positions are saved', async () => {
    draw(stubFetch({ a: { x: 5, y: 6 } }))
    await waitForGraph()
    expect(lastG6()!.options.layout).toBe(false)
  })

  it('PUTs the debounced drag map to /layout', async () => {
    vi.useFakeTimers()
    try {
      draw(stubFetch())
      await waitForGraph()
      const g = lastG6()!
      g.elementPositions = { a: { x: 42, y: 43 } }
      g.handlers['node:dragend']({})
      vi.advanceTimersByTime(800)
      await vi.advanceTimersByTimeAsync(0)
      expect(savedBody?.positions).toEqual({ a: { x: 42, y: 43 } })
    } finally {
      vi.useRealTimers()
    }
  })

  it('重排 DELETEs the row and remounts onto the auto pipeline', async () => {
    const fetchMock = stubFetch({ a: { x: 5, y: 6 } })
    draw(fetchMock)
    await waitForGraph()
    expect(lastG6()!.options.layout).toBe(false)
    await userEvent.click(screen.getByText('重排'))
    await waitForGraph()
    expect(Array.isArray(lastG6()!.options.layout)).toBe(true)
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith('/layout') && i?.method === 'DELETE')).toBe(
      true,
    )
  })
})

describe('GraphOverview focus feedback', () => {
  it('stays quiet when the focus entity is present', async () => {
    draw(stubFetch(null, TRUNCATED_OVERVIEW), 'a')
    // Give the settled data a moment; no toast may appear.
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByText(/未出现在总览中/)).toBeNull()
  })

  it('stays quiet when the overview is not truncated (inspector covers dead links)', async () => {
    draw(stubFetch(null, OVERVIEW), 'http://example.org/Ghost')
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByText(/未出现在总览中/)).toBeNull()
  })

  it('notifies when the focus entity is cut off by a truncated overview', async () => {
    // Deep link ?focus=… pointing outside the truncated overview must not
    // degrade silently (backlog T12①).
    draw(stubFetch(null, TRUNCATED_OVERVIEW), 'http://example.org/Ghost')
    await waitFor(() => expect(screen.getByText(/未出现在总览中/)).toBeTruthy())
  })
})

describe('GraphOverview context menu', () => {
  it('opens create menu on blank right-click and routes 新建子类 to the store', async () => {
    draw(stubFetch())
    await waitForGraph()
    const g = lastG6()!
    g.handlers['canvas:contextmenu']({ client: { x: 10, y: 12 }, preventDefault: vi.fn() })
    expect(await screen.findByRole('menu')).toBeTruthy()
    expect(screen.getByText('＋ 新建类')).toBeTruthy()
    // Blank-canvas menu offers classes only (2026-08-27 user call).
    expect(screen.queryByText('＋ 新建对象属性')).toBeNull()

    g.handlers['node:contextmenu']({
      target: { id: 'a' },
      originalTarget: null,
      client: { x: 10, y: 12 },
      preventDefault: vi.fn(),
    })
    await screen.findByText('新建子类')
    await userEvent.click(screen.getByText('新建子类'))
    expect(useUiStore.getState().entityDialog).toEqual({
      mode: 'subclass',
      parent: 'a',
    })
  })

  it('class menu offers 添加实例; instance nodes get 编辑实例/删除实例 (B2)', async () => {
    const overview: NodesEdges = {
      nodes: [
        { id: 'a', curie: 'ex:A', label: {}, kind: 'class' },
        { id: 'i1', curie: 'ex:Inst', label: {}, kind: 'instance' },
      ],
      edges: [],
      truncated: false,
      totalCount: 2,
    }
    draw(stubFetch(null, overview))
    await waitForGraph()
    const g = lastG6()!
    const rightClick = (id: string) =>
      g.handlers['node:contextmenu']({
        target: { id },
        originalTarget: null,
        client: { x: 10, y: 12 },
        preventDefault: vi.fn(),
      })

    // Class menu: 添加实例 pre-fills the create dialog with the class eid.
    rightClick('a')
    await userEvent.click(await screen.findByText('添加实例'))
    expect(useUiStore.getState().instanceDialog).toEqual({ mode: 'create', parent: 'a' })

    // Instance node: 编辑实例 reveals AND flags auto-edit — the inspector's
    // detail enters its edit mode instead of just re-showing the view state;
    // 删除实例 opens the delete dialog with the instance's local name.
    rightClick('i1')
    await userEvent.click(await screen.findByText('编辑实例'))
    expect(useBrowseStore.getState().selectedEid).toBe('i1')
    expect(useBrowseStore.getState().revealEid).toBe('i1')
    expect(useUiStore.getState().instanceAutoEdit).toBe('i1')
    rightClick('i1')
    await userEvent.click(await screen.findByText('删除 Inst'))
    expect(useUiStore.getState().instanceDialog).toEqual({ mode: 'delete', eid: 'i1' })
  })
})

describe('GraphOverview assertion edges', () => {
  /** Two classes whose badges each reveal one instance; the instances share
   *  one object-property assertion (mirrors the Task 6 backend contract). */
  function assertionStub(opts: { truncated?: boolean } = {}) {
    return vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.includes('/overview'))
        return env({
          nodes: [
            { id: 'a', curie: 'ex:A', label: {}, kind: 'class', instanceCount: 1 },
            { id: 'b', curie: 'ex:B', label: {}, kind: 'class', instanceCount: 1 },
          ],
          edges: [],
          truncated: false,
          totalCount: 2,
        })
      if (u.includes('/entities/a/instances'))
        return env({
          nodes: [{ id: 'i1', curie: 'ex:I1', label: {}, kind: 'instance' }],
          edges: [],
        })
      if (u.includes('/entities/b/instances'))
        return env({
          nodes: [{ id: 'i2', curie: 'ex:I2', label: {}, kind: 'instance' }],
          edges: [],
        })
      if (u.includes('/assertion-edges'))
        return env({
          edges: [{ source: 'i1', target: 'i2', label: 'inspiredBy' }],
          truncated: !!opts.truncated,
          total: opts.truncated ? 900 : 1,
        })
      return env({ positions: {} })
    })
  }

  /** Badge-shaped click on the latest mounted graph (body clicks select). */
  const clickBadge = (id: string) =>
    lastG6()!.handlers['node:click']({
      target: { id },
      originalTarget: { className: 'badge-0', parentElement: null },
    })

  /** Canvas edge rows as MockGraph stores them (post toG6Edges mapping). */
  const canvasEdges = () =>
    (lastG6()!.options.data as { edges?: {
      source: string
      target: string
      data?: { kind?: string }
      style?: { labelText?: string }
    }[] }).edges ?? []

  it('badge reveal pulls assertion edges between revealed instances', async () => {
    draw(assertionStub())
    await waitForGraph()
    clickBadge('a')
    // The revealed instance joins the canvas (a rebuild mounts a new graph).
    await vi.waitFor(() =>
      expect(
        (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes?.some((n) => n.id === 'i1'),
      ).toBe(true),
    )
    clickBadge('b')
    await vi.waitFor(() =>
      expect(
        (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes?.some((n) => n.id === 'i2'),
      ).toBe(true),
    )
    // With both ends revealed, the assertion edge lands as a green-ish
    // canvas edge carrying the property's local name as its label.
    await vi.waitFor(() => {
      const hit = canvasEdges().find((e) => e.source === 'i1' && e.target === 'i2')
      expect(hit?.data?.kind).toBe('assertion')
      expect(hit?.style?.labelText).toBe('inspiredBy')
    })
  })

  it('multi-type instances stay unique when two classes share one instance', async () => {
    // Manager ↔ FullTimeEmployee both carry james-anderson (direct rdf:type
    // both ways): the payload concat fed G6 duplicate node ids and whited
    // the page. The merged canvas data must keep ids unique.
    const shared = { id: 'shared', curie: 'ex:S', label: {}, kind: 'instance' as const }
    const stub = vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.includes('/overview'))
        return env({
          nodes: [
            { id: 'a', curie: 'ex:A', label: {}, kind: 'class', instanceCount: 1 },
            { id: 'b', curie: 'ex:B', label: {}, kind: 'class', instanceCount: 2 },
          ],
          edges: [],
          truncated: false,
          totalCount: 2,
        })
      if (u.includes('/entities/a/instances'))
        return env({ nodes: [shared], edges: [] })
      if (u.includes('/entities/b/instances'))
        return env({
          nodes: [shared, { id: 'other', curie: 'ex:O', label: {}, kind: 'instance' }],
          edges: [],
        })
      if (u.includes('/assertion-edges')) return env({ edges: [], truncated: false, total: 0 })
      return env({ positions: {} })
    })
    draw(stub)
    await waitForGraph()
    clickBadge('a')
    await vi.waitFor(() =>
      expect(
        (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes?.some((n) => n.id === 'shared'),
      ).toBe(true),
    )
    clickBadge('b')
    await vi.waitFor(() =>
      expect(
        (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes?.some((n) => n.id === 'other'),
      ).toBe(true),
    )
    const ids = (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes!.map((n) => n.id)
    expect(ids.filter((id) => id === 'shared')).toHaveLength(1)
  })

  it('truncated assertion edges toast once per revealed set', async () => {
    draw(assertionStub({ truncated: true }))
    await waitForGraph()
    clickBadge('a')
    await vi.waitFor(() =>
      expect(
        (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes?.some((n) => n.id === 'i1'),
      ).toBe(true),
    )
    clickBadge('b')
    await vi.waitFor(() => expect(screen.getByText(/断言边过多/)).toBeTruthy())
    // Collapsing and re-expanding the same badge set hits the same cached
    // truncated payload — the notice must not repeat.
    clickBadge('b')
    await new Promise((r) => setTimeout(r, 50))
    clickBadge('b')
    await vi.waitFor(() =>
      expect(
        (lastG6()!.options.data as { nodes?: { id: string }[] }).nodes?.some((n) => n.id === 'i2'),
      ).toBe(true),
    )
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.getAllByText(/断言边过多/)).toHaveLength(1)
  })
})

describe('GraphOverview deprecated visibility', () => {
  it('fetches with includeDeprecated=false, refetches with true on toggle', async () => {
    const fetchMock = stubFetch()
    draw(fetchMock)
    await waitForGraph()
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).includes('/overview?includeDeprecated=false')),
    ).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: '显示已废弃' }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).includes('/overview?includeDeprecated=true')),
      ).toBe(true),
    )
  })

  it('notes the hidden deprecated count until the toggle is on', async () => {
    draw(stubFetch(null, { ...OVERVIEW, deprecatedCount: 2 }))
    await waitForGraph()
    expect(screen.getByText('已隐藏 2 个废弃条目')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '显示已废弃' }))
    await waitFor(() => expect(screen.queryByText('已隐藏 2 个废弃条目')).toBeNull())
  })

  it('stays quiet when nothing is deprecated', async () => {
    draw(stubFetch())
    await waitForGraph()
    expect(screen.queryByText(/废弃条目/)).toBeNull()
  })
})

function waitForGraph() {
  return vi.waitFor(() => {
    if (!lastG6()) throw new Error('graph not mounted yet')
  })
}

/* Task 15 (progressive canvas): the overview serves folded roots; clicking
   the fold badge expands via GET /expand and merges the children in, clicking
   again collects the expanded subtree and removes it. */

describe('GraphOverview progressive fold', () => {
  const PROG: NodesEdges = {
    nodes: [
      { id: 'root', curie: 'ex:Root', label: {}, kind: 'class', folded: true, subtreeSize: 3 },
      {
        id: '__deprecated__',
        curie: '__deprecated__',
        label: {},
        kind: 'deprecatedBucket',
        folded: true,
        subtreeSize: 2,
      },
    ],
    edges: [],
    truncated: false,
    totalCount: 5,
    mode: 'progressive',
    liveCount: 3,
    deprecatedCount: 2,
  }
  const EXPAND: NodesEdges = {
    nodes: [{ id: 'kid', curie: 'ex:Kid', label: {}, kind: 'class', folded: true, subtreeSize: 1 }],
    edges: [{ source: 'kid', target: 'root', kind: 'subClassOf' }],
    truncated: false,
    totalCount: 1,
  }

  function drawProgressive() {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/overview')) return env(PROG)
      if (u.includes('/expand')) return env(EXPAND)
      if (u.endsWith('/layout') && init?.method === 'PUT') {
        savedBody = JSON.parse(String(init.body))
        return env(savedBody)
      }
      return env({ positions: {} })
    })
    draw(fetchMock)
    return fetchMock
  }

  it('serves folded roots; the bucket label reads 已废弃', async () => {
    drawProgressive()
    await waitForGraph()
    const ids = () =>
      (
        lastG6()!.options.data as {
          nodes: { id: string; style?: { badges?: { text: string }[]; labelText?: string } }[]
        }
      ).nodes
    expect(ids().map((n) => n.id)).toEqual(['root', '__deprecated__'])
    expect(ids()[0].style?.badges?.[0].text).toBe('+3')
    expect(ids()[1].style?.badges?.[0].text).toBe('+2')
    expect(ids()[1].style?.labelText).toBe('已废弃')
  })

  it('fold click fetches /expand and merges children; clicking again removes them', async () => {
    const fetchMock = drawProgressive()
    await waitForGraph()
    const g = lastG6()!
    // Wait for the rebuilt graph (a new Graph mounts per data change).
    g.handlers['node:click']({
      target: { id: 'root' },
      originalTarget: { className: 'badge-0' },
    })
    await vi.waitFor(() => {
      const latest = [...g6Instances()].at(-1)!
      const got = (latest.options.data as { nodes: { id: string }[] }).nodes.map((n) => n.id)
      expect(got).toEqual(['root', '__deprecated__', 'kid'])
    })
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/entities/root/expand'))).toBe(
      true,
    )
    // Collapse: the subtree under root leaves the canvas again.
    const latest = [...g6Instances()].at(-1)!
    latest.handlers['node:click']({
      target: { id: 'root' },
      originalTarget: { className: 'badge-0' },
    })
    await vi.waitFor(() => {
      const after = [...g6Instances()].at(-1)!
      const got = (after.options.data as { nodes: { id: string }[] }).nodes.map((n) => n.id)
      expect(got).toEqual(['root', '__deprecated__'])
    })
  })
})

describe('GraphOverview insertion layout on expand', () => {
  const PROG: NodesEdges = {
    nodes: [{ id: 'root', curie: 'ex:Root', label: {}, kind: 'class', folded: true, subtreeSize: 2 }],
    edges: [],
    truncated: false,
    totalCount: 3,
    mode: 'progressive',
    liveCount: 3,
  }
  const EXPAND: NodesEdges = {
    nodes: [{ id: 'kid', curie: 'ex:Kid', label: {}, kind: 'class', folded: true, subtreeSize: 1 }],
    edges: [{ source: 'kid', target: 'root', kind: 'subClassOf' }],
    truncated: false,
    totalCount: 1,
  }

  it('expanded children land under the saved parent spot, canvas stays explicit', async () => {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/overview')) return env(PROG)
      if (u.includes('/expand')) return env(EXPAND)
      if (u.endsWith('/layout') && init?.method === 'PUT') {
        savedBody = JSON.parse(String(init.body))
        return env(savedBody)
      }
      return env({ positions: { root: { x: 100, y: 0 } } })
    })
    draw(fetchMock)
    await waitForGraph()
    expect(lastG6()!.options.layout).toBe(false) // saved canvas, explicit coords
    lastG6()!.handlers['node:click']({
      target: { id: 'root' },
      originalTarget: { className: 'badge-0' },
    })
    await vi.waitFor(() => {
      const latest = [...g6Instances()].at(-1)!
      expect((latest.options.data as { nodes: { id: string }[] }).nodes.map((n) => n.id)).toEqual(
        ['root', 'kid'],
      )
    })
    const latest = [...g6Instances()].at(-1)!
    // Still the explicit pipeline; the kid carries inserted coordinates one
    // row under the saved parent spot (100, 0) → (100, 90).
    expect(latest.options.layout).toBe(false)
    const kid = (
      latest.options.data as { nodes: { id: string; style?: { x?: number; y?: number } }[] }
    ).nodes.find((n) => n.id === 'kid')!
    expect(kid.style?.x).toBe(100)
    expect(kid.style?.y).toBe(90)
  })
})

/* Task 17: session-level view override (auto|full|progressive) rides the
   overview URL; in progressive mode revealing an off-canvas entity resets
   the canvas to that entity plus its foldable children. */

describe('GraphOverview view override and reveal anchor', () => {
  const PROG: NodesEdges = {
    nodes: [{ id: 'root', curie: 'ex:Root', label: {}, kind: 'class', folded: true, subtreeSize: 3 }],
    edges: [],
    truncated: false,
    totalCount: 4,
    mode: 'progressive',
    liveCount: 4,
  }
  const ENTITY = {
    eid: 'http://x/Far',
    curie: 'ex:Far',
    type: 'Class',
    label: { en: 'Far' },
    comment: null,
    deprecated: false,
    parents: [],
    children: [],
    properties: [],
    referencedBy: [],
    axioms: [],
    stats: { directChildren: 0, totalDescendants: 0 },
  }
  const FAR = 'http://x/Far'
  const EXPAND: NodesEdges = {
    nodes: [{ id: 'kid', curie: 'ex:Kid', label: {}, kind: 'class', folded: true, subtreeSize: 1 }],
    edges: [{ source: 'kid', target: FAR, kind: 'subClassOf' }],
    truncated: false,
    totalCount: 1,
  }

  function drawOverride() {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/overview')) return env(PROG)
      if (u.endsWith(`/entities/${encodeURIComponent(FAR)}/expand`)) return env(EXPAND)
      if (u.endsWith(`/entities/${encodeURIComponent(FAR)}`)) return env(ENTITY)
      if (u.endsWith('/layout') && init?.method === 'PUT') {
        savedBody = JSON.parse(String(init.body))
        return env(savedBody)
      }
      return env({ positions: {} })
    })
    draw(fetchMock)
    return fetchMock
  }

  it('renders 全图/渐进 toggles; 全图 refetches with view=full', async () => {
    const fetchMock = drawOverride()
    await waitForGraph()
    await userEvent.click(screen.getByRole('button', { name: '全图' }))
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes('view=full'))).toBe(true)
    })
    await userEvent.click(screen.getByRole('button', { name: '渐进' }))
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes('view=progressive'))).toBe(true)
    })
  })

  it('progressive reveal of an off-canvas entity anchors the canvas there', async () => {
    const fetchMock = drawOverride()
    await waitForGraph()
    useBrowseStore.getState().reveal(FAR)
    await vi.waitFor(() => {
      const latest = [...g6Instances()].at(-1)!
      const ids = (latest.options.data as { nodes: { id: string }[] }).nodes.map((n) => n.id)
      expect(ids).toEqual([FAR, 'kid'])
    })
    expect(
      fetchMock.mock.calls.some(([u]) =>
        String(u).endsWith(`/entities/${encodeURIComponent(FAR)}/expand`),
      ),
    ).toBe(true)
    expect(
      fetchMock.mock.calls.some(([u]) =>
        String(u).endsWith(`/entities/${encodeURIComponent(FAR)}`),
      ),
    ).toBe(true)
  })
})
