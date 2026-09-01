import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GEdge } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
import { lastG6, MockGraph, resetG6 } from '../test/g6Mock'
import GraphView, { toG6Edges, toG6Nodes, type GraphViewNode, type KindFilter } from './GraphView'
import { FAST_LAYOUT_NODES, MIN_AUTO_ZOOM } from './linearTree'

/* G6 renders on canvas, which jsdom cannot provide — the module is mocked and
   assertions target (a) the DOM overlays (legend/controls, real) and (b) the
   data passed into the mocked Graph (constructor data / setData / update*).
   Pure mappings are covered directly below. */

vi.mock('@antv/g6', async () => {
  const mock = await import('../test/g6Mock')
  return {
    Graph: mock.MockGraph,
    BaseLayout: mock.BaseLayout,
    register: mock.register,
    ExtensionCategory: mock.ExtensionCategory,
  }
})

const TOKENS = {
  primary: '#4f46e5',
  primaryFg: '#ffffff',
  panel: '#ffffff',
  line: '#e2e8f0',
  ink: '#0f172a',
  ink3: '#94a3b8',
  edgeSub: '#8b5cf6',
  success: '#10b981',
  mono: 'mono',
}

const NODES: GraphViewNode[] = [
  { id: 'a', curie: 'ex:A', label: {}, kind: 'class', highlighted: true, instanceCount: 3 },
  { id: 'b', curie: 'ex:B', label: {}, kind: 'class' },
  { id: 'c', curie: 'ex:C', label: {}, kind: 'class' },
  { id: 'p', curie: 'ex:hasTopping', label: {}, kind: 'property', ptype: 'ObjectProperty' },
  { id: 'd', curie: 'ex:age', label: {}, kind: 'property', ptype: 'DatatypeProperty' },
  { id: 'i1', curie: 'ex:rex', label: {}, kind: 'instance' },
]

const EDGES: GEdge[] = [
  { source: 'b', target: 'a', kind: 'subClassOf' },
  { source: 'c', target: 'a', kind: 'subClassOf' },
  { source: 'a', target: 'p', kind: 'property' },
  { source: 'a', target: 'd', kind: 'datatype' },
]

/** The overview's opening state: classes only, properties wait off-stage. */
const CLASS_ONLY: KindFilter = { classes: true, objectProps: false, dataProps: false }

function draw(extra: Record<string, unknown> = {}, onSelect = vi.fn()) {
  const view = render(
    <ThemeProvider>
      <GraphView nodes={NODES} edges={EDGES} onSelect={onSelect} {...extra} />
    </ThemeProvider>,
  )
  return { view, onSelect }
}

interface G6Datum {
  id: string
  style: Record<string, unknown> & { badges?: { text: string }[] }
}

const lastData = (from: 'constructor' | 'setData' = 'constructor') => {
  const g = lastG6()
  if (!g) throw new Error('no graph instance')
  const raw = from === 'constructor' ? g.options.data : g.setData.mock.lastCall?.[0]
  return raw as {
    nodes: G6Datum[]
    edges: {
      id: string
      source: string
      target: string
      type?: string
      style: Record<string, unknown> & { curveOffset?: number }
      data?: { kind?: string }
    }[]
  }
}

beforeEach(() => {
  localStorage.clear()
  resetG6()
})

afterEach(() => {
  cleanup()
})

describe('GraphView', () => {
  it('passes every node (local-name labels, instance badge) and edge to the canvas', () => {
    draw()
    const { nodes, edges } = lastData()
    // Labels show local names (prefix stripped); focus keeps no star.
    expect(nodes.map((n) => n.style.labelText)).toEqual(['A', 'B', 'C', 'hasTopping', 'age', 'rex'])
    // Badge = the class's direct instance count (a has 3).
    expect(nodes.find((n) => n.id === 'a')?.style.badges?.[0].text).toBe('3')
    expect(nodes.find((n) => n.id === 'b')?.style.badges).toBeUndefined()
    expect(edges).toHaveLength(4)
    // Legend and zoom controls render as DOM overlays; the kind toggles use
    // the short 对象/数据 labels, the legend spells them out.
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
    expect(screen.getByText('对象属性')).toBeTruthy()
    expect(screen.getByText('数据属性')).toBeTruthy()
    expect(screen.getByText('实例')).toBeTruthy()
    expect(screen.getByRole('button', { name: '对象' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '数据' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '适配' })).toBeTruthy()
  })

  it('lays out as a dagre → rank-wrap pipeline with orthogonal edges', () => {
    draw()
    const opts = lastG6()!.options as Record<string, unknown>
    const layout = opts.layout as { type: string }[]
    expect(layout).toHaveLength(2)
    expect(layout[0]).toMatchObject({ type: 'antv-dagre', rankdir: 'TB', nodesep: 48 })
    expect(layout[1]).toMatchObject({ type: 'rank-wrap', targetRowWidth: 1700 })
    // No options-level edge type: it would override the per-datum types the
    // parallel-edge fan depends on (G6 resolves options.edge.type first).
    expect(opts.edge).toBeUndefined()
    // Singletons stay orthogonal polylines, carried per datum.
    const single = lastData().edges.every((e) => e.type === 'polyline')
    expect(single).toBe(true)
  })

  it('defaultKinds seeds the uncontrolled filter (overview opens class-only)', () => {
    draw({ defaultKinds: CLASS_ONLY })
    const ids = lastData().nodes.map((n: { id: string }) => n.id)
    // Property nodes are hidden from the first render; instances stay.
    expect(ids).not.toContain('p')
    expect(ids).toEqual(expect.arrayContaining(['a', 'b', 'c', 'i1']))
  })

  it('focuses the focusId entity after the first render', async () => {
    draw({ focusId: 'a' })
    const g = lastG6() as MockGraph
    await waitFor(() => expect(g.focusElement).toHaveBeenCalledWith('a'))
  })

  it('reports node clicks through onSelect', () => {
    const { onSelect } = draw()
    const g = lastG6() as MockGraph
    g.handlers['node:click']({ target: { id: 'b' } })
    expect(onSelect).toHaveBeenCalledWith('b')
  })

  it('routes badge clicks to onBadgeClick, body clicks to onSelect', () => {
    const onSelect = vi.fn()
    const onBadgeClick = vi.fn()
    render(
      <ThemeProvider>
        <GraphView
          nodes={NODES}
          edges={EDGES}
          onSelect={onSelect}
          onBadgeClick={onBadgeClick}
        />
      </ThemeProvider>,
    )
    const g = lastG6() as MockGraph
    /* Real G6 5.1.1 event shape (runtime/behavior.js): target is the node
       element, originalTarget the innermost hit shape. A badge click hits
       the badge label's text shape; sub-shapes carry className (never name). */
    g.handlers['node:click']({
      target: { id: 'b' },
      originalTarget: { className: 'text', parentElement: { className: 'badge-0' } },
    })
    expect(onBadgeClick).toHaveBeenCalledWith('b')
    expect(onSelect).not.toHaveBeenCalled()
    // Direct hit on the badge shape itself works the same.
    g.handlers['node:click']({ target: { id: 'b' }, originalTarget: { className: 'badge-0' } })
    expect(onBadgeClick).toHaveBeenCalledTimes(2)
    // A body click hits the key shape — plain select.
    g.handlers['node:click']({ target: { id: 'b' }, originalTarget: { className: 'key' } })
    expect(onSelect).toHaveBeenCalledWith('b')
  })

  it('toggles the edge-label switch off and back on', async () => {
    draw()
    expect(screen.getByRole('button', { name: '标签' }).getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(screen.getByRole('button', { name: '标签' }))
    expect(screen.getByRole('button', { name: '标签' }).getAttribute('aria-pressed')).toBe('false')
    const g = lastG6() as MockGraph
    const off = g.updateEdgeData.mock.lastCall?.[0] as { style: { labelText: string } }[]
    expect(off.every((e) => e.style.labelText === '')).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: '标签' }))
    const on = g.updateEdgeData.mock.lastCall?.[0] as { style: { labelText: string } }[]
    expect(on.map((e) => e.style.labelText)).toEqual([
      'subClassOf',
      'subClassOf',
      'hasTopping',
      'age',
    ])
  })

  it('combines kind dimensions: 类 + 对象属性 coexist on one canvas', async () => {
    draw({ defaultKinds: CLASS_ONLY })
    await userEvent.click(screen.getByRole('button', { name: '对象' }))
    const data = lastData('setData')
    // Classes (and their instances) plus the object property — together.
    expect(data.nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'c', 'i1', 'p'])
    expect(data.edges.some((e) => e.source === 'a' && e.target === 'p')).toBe(true)
    // The datatype property stays hidden — dimensions are independent.
    expect(data.nodes.map((n) => n.id)).not.toContain('d')
  })

  it('数据属性 toggles independently of 对象属性', async () => {
    draw({ defaultKinds: CLASS_ONLY })
    await userEvent.click(screen.getByRole('button', { name: '数据' }))
    const data = lastData('setData')
    expect(data.nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'c', 'd', 'i1'])
  })

  it('全部 switches every dimension on and reads pressed while all are on', async () => {
    draw({ defaultKinds: CLASS_ONLY })
    expect(screen.getByRole('button', { name: '全部' }).getAttribute('aria-pressed')).toBe('false')
    await userEvent.click(screen.getByRole('button', { name: '全部' }))
    const ids = lastData('setData').nodes.map((n) => n.id).sort()
    expect(ids).toEqual(['a', 'b', 'c', 'd', 'i1', 'p'])
    expect(screen.getByRole('button', { name: '全部' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('prevents emptying the canvas: the last active dimension stays on', async () => {
    draw({ defaultKinds: CLASS_ONLY })
    const g = lastG6() as MockGraph
    await waitFor(() => expect(g.render).toHaveBeenCalled()) // mount settled
    // Classes are the only active dimension — switching them off would empty
    // the canvas, so the toggle refuses (no setData at all).
    await userEvent.click(screen.getByRole('button', { name: '类' }))
    expect(g.setData).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '类' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('hides the zoom controls when showControls is false', () => {
    draw({ showControls: false })
    expect(screen.queryByRole('button', { name: '适配' })).toBeNull()
    // The legend stays regardless.
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
  })

  it('rides the filter toggles inside the shared bottom control cluster', () => {
    draw()
    const cluster = screen.getByRole('button', { name: '适配' }).closest('div')
    expect(cluster).toBeTruthy()
    // One bar, two segments: the filter group joins the view ops cluster
    // instead of floating alone in the top-right corner.
    expect(cluster!.contains(screen.getByRole('button', { name: '标签' }))).toBe(true)
    expect(cluster!.contains(screen.getByRole('button', { name: '全部' }))).toBe(true)
  })

  it('fans parallel edges out instead of stacking them', () => {
    // Two assertion properties between the same instance pair (the Sofia ↔
    // James case): the same-direction pair becomes two quadratic arcs with
    // opposite curve offsets; every other edge stays an orthogonal polyline.
    draw({
      edges: [
        ...EDGES,
        { source: 'i1', target: 'b', kind: 'assertion', label: 'worksIn' },
        { source: 'i1', target: 'b', kind: 'assertion', label: 'manages' },
      ],
    })
    const fan = lastData().edges.filter((e) => e.source === 'i1' && e.target === 'b')
    expect(fan).toHaveLength(2)
    expect(fan.map((e) => e.type)).toEqual(['quadratic', 'quadratic'])
    expect(fan.map((e) => e.style.curveOffset)).toEqual([20, -20])
    // A singleton edge elsewhere on the canvas keeps its polyline.
    const other = lastData().edges.find((e) => e.source === 'a' && e.target === 'p')
    expect(other?.type).toBe('polyline')
    expect(other?.style.curveOffset).toBeUndefined()
  })

  it('fans reversed-direction pairs with same-sign offsets (manages ↔ reportsTo)', () => {
    // The class-level objectProperty case: manages (Manager→Employee) and
    // reportsTo (Employee→Manager) share the unordered pair. Same-sign
    // offsets, because curveOffset is relative to each edge's own direction.
    draw({
      edges: [
        ...EDGES,
        { source: 'b', target: 'c', kind: 'objectProperty', label: 'manages' },
        { source: 'c', target: 'b', kind: 'objectProperty', label: 'reportsTo' },
      ],
    })
    const fan = lastData().edges.filter(
      (e) => (e.source === 'b' && e.target === 'c') || (e.source === 'c' && e.target === 'b'),
    )
    expect(fan).toHaveLength(2)
    expect(fan.map((e) => e.style.curveOffset)).toEqual([20, 20])
  })

  it('toggles the legend from the control bar', async () => {
    draw()
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '图例' }))
    expect(screen.queryByText('子类（subClassOf）')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '图例' }))
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
  })

  it('shows objectProperty edges only with the 对象属性 filter on', async () => {
    draw({
      edges: [
        ...EDGES,
        { source: 'b', target: 'c', kind: 'objectProperty', label: 'worksIn', eid: 'http://ex/worksIn' },
      ],
      defaultKinds: CLASS_ONLY,
    })
    const kinds = (d: { edges: { data?: { kind?: string } }[] }) =>
      d.edges.map((e) => e.data?.kind)
    // Class-only opening state: the direct edge waits off-stage.
    expect(kinds(lastData('constructor'))).not.toContain('objectProperty')
    await userEvent.click(screen.getByRole('button', { name: '对象' }))
    expect(kinds(lastData('setData'))).toContain('objectProperty')
  })

  it('routes an objectProperty edge click to the property detail', async () => {
    const onSelect = vi.fn()
    draw(
      {
        edges: [
          ...EDGES,
          { source: 'b', target: 'c', kind: 'objectProperty', label: 'worksIn', eid: 'http://ex/worksIn' },
        ],
        defaultKinds: CLASS_ONLY,
      },
      onSelect,
    )
    await userEvent.click(screen.getByRole('button', { name: '对象' }))
    const g = lastG6()!
    const edge = lastData('setData').edges.find((e) => e.data?.kind === 'objectProperty')
    expect(edge).toBeTruthy()
    g.handlers['edge:click']({
      target: { id: edge!.id },
      originalTarget: null,
      preventDefault: vi.fn(),
    })
    expect(onSelect).toHaveBeenCalledWith('http://ex/worksIn')
  })
})

describe('toG6Edges', () => {
  const all = new Map([
    ['a', 'ex:A'],
    ['b', 'ex:B'],
    ['c', 'ex:C'],
    ['d', 'ex:age'],
    ['i1', 'ex:rex'],
    ['p', 'ex:hasTopping'],
  ])
  const edges: GEdge[] = [
    { source: 'b', target: 'a', kind: 'subClassOf' },
    { source: 'a', target: 'p', kind: 'property' },
    { source: 'a', target: 'd', kind: 'datatype' },
    { source: 'a', target: 'ghost', kind: 'subClassOf' },
  ]

  it('labels an objectProperty edge with its property name and eid', () => {
    const mapped = toG6Edges(
      [{ source: 'b', target: 'c', kind: 'objectProperty', label: 'worksIn', eid: 'http://ex/worksIn' }],
      all,
      true,
      TOKENS,
    )
    expect(mapped).toHaveLength(1)
    expect(mapped[0].style).toMatchObject({ labelText: 'worksIn', stroke: TOKENS.primary })
    expect(mapped[0].data).toMatchObject({ kind: 'objectProperty', propEid: 'http://ex/worksIn' })
  })

  it('encodes the three edge semantics via tokens with matching arrows', () => {
    const mapped = toG6Edges(edges, all, false, TOKENS)
    const st = (e: { style?: Record<string, unknown> }) => e.style ?? {}
    expect(mapped).toHaveLength(3) // edge to a filtered-out endpoint is dropped
    expect(st(mapped[0])).toMatchObject({ stroke: '#8b5cf6', lineDash: [6, 5], startArrow: true })
    expect(st(mapped[1])).toMatchObject({ stroke: '#4f46e5', endArrowFill: '#4f46e5' })
    expect(st(mapped[1]).lineDash).toBeUndefined()
    expect(st(mapped[2])).toMatchObject({ stroke: '#94a3b8', lineDash: [1, 4] })
  })

  it('reverses attach edges so dagre reads top-down, arrow keeps pointing at the parent', () => {
    // subClassOf/instance arrive child→class; dagre TB places a datum's
    // source above its target, so attach edges are swapped (parent above
    // child) and the arrow moves to the start — on screen it still points
    // at the parent/class. Property edges keep class→property as-is.
    const attach: GEdge[] = [
      { source: 'b', target: 'a', kind: 'subClassOf' },
      { source: 'i1', target: 'a', kind: 'instance' },
      { source: 'a', target: 'p', kind: 'property' },
    ]
    const mapped = toG6Edges(attach, all, false, TOKENS)
    const st = (e: { style?: Record<string, unknown> }) => e.style ?? {}
    expect(mapped[0]).toMatchObject({ source: 'a', target: 'b' })
    expect(st(mapped[0])).toMatchObject({ startArrow: true })
    expect(st(mapped[0]).endArrow).toBeUndefined()
    expect(mapped[1]).toMatchObject({ source: 'a', target: 'i1' })
    expect(st(mapped[1])).toMatchObject({ startArrow: true })
    expect(mapped[2]).toMatchObject({ source: 'a', target: 'p' })
    expect(st(mapped[2])).toMatchObject({ endArrow: true })
  })

  it('labels edges only when enabled — property edges by local name, not kind', () => {
    const st = (e: { style?: Record<string, unknown> }) => e.style ?? {}
    const withInstance = [...edges, { source: 'i1', target: 'a', kind: 'instance' }]
    expect(toG6Edges(withInstance, all, true, TOKENS).map((e) => st(e).labelText)).toEqual([
      'subClassOf',
      'hasTopping',
      'age',
      'instance',
    ])
    expect(toG6Edges(edges, all, false, TOKENS).every((e) => st(e).labelText === '')).toBe(true)
  })
})

describe('toG6Nodes', () => {
  it('keeps cards compact: min 72px wide, 6.6px per curie char', () => {
    const mapped = toG6Nodes(NODES, TOKENS)
    // 'ex:B' (4 chars) floors at the 72px minimum.
    const b = mapped.find((n) => n.id === 'b') as G6Datum
    expect(b.style.size).toEqual([72, 32])
  })

  it('styles the highlighted entity and property nodes apart from classes', () => {
    const mapped = toG6Nodes(NODES, TOKENS)
    const by = (id: string) => mapped.find((n) => n.id === id) as G6Datum
    // Highlighted: 2px primary border, bold label — no star.
    expect(by('a').style).toMatchObject({ stroke: '#4f46e5', lineWidth: 2, labelFontWeight: 700 })
    expect(by('a').style.labelText).toBe('A')
    // Instance nodes prefer their human label, falling back to the local name.
    expect(by('i1').style.labelText).toBe('rex')
    const named = toG6Nodes([...NODES, { id: 'i2', curie: 'ex:fido', label: { en: 'Fido' }, kind: 'instance' }], TOKENS)
    expect(named.find((n) => n.id === 'i2')?.style?.labelText).toBe('Fido')
    // Property node: dashed violet border.
    expect(by('p').style).toMatchObject({ stroke: '#8b5cf6', lineDash: [4, 3] })
    // Plain class: solid grey border, no dash, no badge.
    expect(by('b').style).toMatchObject({ stroke: '#e2e8f0' })
    expect(by('b').style.lineDash).toBeUndefined()
    expect(by('b').style.badges).toBeUndefined()
  })

  it('styles instances as small grey circles with a side label', () => {
    const mapped = toG6Nodes(NODES, TOKENS)
    const inst = mapped.find((n) => n.id === 'i1') as G6Datum
    expect(inst.style).toMatchObject({
      size: 12,
      stroke: '#94a3b8',
      labelPlacement: 'right',
      labelFontSize: 10,
    })
    expect(inst.style.badges).toBeUndefined()
    expect(inst.style.radius).toBeUndefined()
  })
})

describe('GraphView saved layout', () => {
  it('disables the auto pipeline and injects coordinates when positions are saved', () => {
    draw({ savedPositions: { a: { x: 10, y: 20 }, b: { x: 30, y: 40 } } })
    const g = lastG6()!
    expect(g.options.layout).toBe(false)
    const { nodes } = lastData()
    expect(nodes.find((n) => n.id === 'a')?.style.x).toBe(10)
    expect(nodes.find((n) => n.id === 'b')?.style.y).toBe(40)
    // Unsaved nodes get deterministic fallbacks: c (child of a) beside a.
    expect(nodes.find((n) => n.id === 'c')?.style).toMatchObject({ x: 250, y: 20 })
  })

  it('keeps the layout pipeline and injects no coordinates when nothing is saved', () => {
    draw()
    expect(Array.isArray(lastG6()!.options.layout)).toBe(true)
    expect(lastData().nodes.find((n) => n.id === 'a')?.style.x).toBeUndefined()
  })

  it('debounces drag-end into a whole-map onLayoutChange', () => {
    vi.useFakeTimers()
    try {
      const onLayoutChange = vi.fn()
      draw({ onLayoutChange })
      const g = lastG6()!
      // Simulate rendered positions: G6 5.x keeps them on the element, not
      // the data model (whose style.x stays stale after drags).
      g.elementPositions = Object.fromEntries(
        NODES.map((n, i) => [n.id, { x: i * 100, y: 50 }]),
      )
      g.handlers['node:dragend']({})
      expect(onLayoutChange).not.toHaveBeenCalled()
      vi.advanceTimersByTime(800)
      expect(onLayoutChange).toHaveBeenCalledTimes(1)
      const arg = onLayoutChange.mock.lastCall?.[0] as Record<string, { x: number }>
      expect(Object.keys(arg).sort()).toEqual(['a', 'b', 'c', 'd', 'i1', 'p'])
      expect(arg.a).toEqual({ x: 0, y: 50 })
      expect(arg.p).toEqual({ x: 300, y: 50 })
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders the 重排 escape hatch only when onResetLayout is wired', async () => {
    draw()
    expect(screen.queryByText('重排')).toBeNull()
    const onResetLayout = vi.fn()
    draw({ onResetLayout })
    await userEvent.click(screen.getByText('重排'))
    expect(onResetLayout).toHaveBeenCalledTimes(1)
  })
})

describe('GraphView context menu reporting', () => {
  it('reports node right-clicks with container-relative coordinates', () => {
    const onContextMenu = vi.fn()
    draw({ onContextMenu })
    const g = lastG6()!
    const preventDefault = vi.fn()
    g.handlers['node:contextmenu']({
      target: { id: 'b' },
      originalTarget: null,
      client: { x: 30, y: 40 },
      preventDefault,
    })
    expect(preventDefault).toHaveBeenCalled()
    expect(onContextMenu).toHaveBeenCalledWith(
      expect.objectContaining({ targetId: 'b', kind: 'class', curie: 'ex:B' }),
    )
    const info = onContextMenu.mock.lastCall?.[0] as { x: number; y: number }
    expect(typeof info.x).toBe('number')
    expect(typeof info.y).toBe('number')
  })

  it('reports blank-canvas right-clicks without a target', () => {
    const onContextMenu = vi.fn()
    draw({ onContextMenu })
    const g = lastG6()!
    g.handlers['canvas:contextmenu']({ client: { x: 5, y: 6 }, preventDefault: vi.fn() })
    expect(onContextMenu).toHaveBeenCalledWith(
      expect.objectContaining({ targetId: undefined }),
    )
  })
})

describe('oversized auto layout (linear tree path)', () => {
  it('skips the dagre pipeline past FAST_LAYOUT_NODES and seeds every position', () => {
    const big: GraphViewNode[] = [{ id: 'root', curie: 'ex:Root', label: {}, kind: 'class' }]
    const bigEdges: GEdge[] = []
    for (let i = 0; i < FAST_LAYOUT_NODES + 5; i++) {
      big.push({ id: `n${i}`, curie: `ex:N${i}`, label: {}, kind: 'class' })
      bigEdges.push({ source: `n${i}`, target: 'root', kind: 'subClassOf' })
    }
    render(
      <ThemeProvider>
        <GraphView nodes={big} edges={bigEdges} defaultKinds={CLASS_ONLY} onSelect={vi.fn()} />
      </ThemeProvider>,
    )
    // The auto pipeline is replaced by precomputed coordinates.
    expect(lastG6()!.options.layout).toBe(false)
    const placed = lastData().nodes.filter(
      (n) => typeof n.style.x === 'number' && typeof n.style.y === 'number',
    )
    expect(placed).toHaveLength(big.length)
  })

  it('keeps the dagre pipeline below the threshold', () => {
    draw({ defaultKinds: CLASS_ONLY })
    const layout = lastG6()!.options.layout as unknown as { type: string }[]
    expect(Array.isArray(layout)).toBe(true)
    expect(layout[0].type).toBe('antv-dagre')
  })
})

describe('fitView zoom clamp', () => {
  it('raises the zoom floor after an over-shrunk fit (oversized maps stay visible)', async () => {
    const big: GraphViewNode[] = [{ id: 'root', curie: 'ex:Root', label: {}, kind: 'class' }]
    const bigEdges: GEdge[] = []
    for (let i = 0; i < FAST_LAYOUT_NODES + 5; i++) {
      big.push({ id: `n${i}`, curie: `ex:N${i}`, label: {}, kind: 'class' })
      bigEdges.push({ source: `n${i}`, target: 'root', kind: 'subClassOf' })
    }
    render(
      <ThemeProvider>
        <GraphView nodes={big} edges={bigEdges} defaultKinds={CLASS_ONLY} onSelect={vi.fn()} />
      </ThemeProvider>,
    )
    const g = lastG6()!
    // fitView landed at ~2% on a 36k-px-tall map — invisible dots.
    g.getZoom.mockReturnValue(0.02)
    await waitFor(() => expect(g.fitView).toHaveBeenCalled())
    await waitFor(() => expect(g.zoomTo).toHaveBeenCalledWith(MIN_AUTO_ZOOM))
  })

  it('leaves a comfortable fit alone (no zoomTo)', async () => {
    draw({ defaultKinds: CLASS_ONLY })
    const g = lastG6()!
    g.getZoom.mockReturnValue(0.8)
    await waitFor(() => expect(g.fitView).toHaveBeenCalled())
    expect(g.zoomTo).not.toHaveBeenCalled()
  })
})

describe('mount effects skip their first run', () => {
  it('does not setData/updateEdgeData on mount — the build effect already rendered', () => {
    draw({ defaultKinds: CLASS_ONLY })
    const g = lastG6()!
    expect(g.setData).not.toHaveBeenCalled()
    expect(g.updateEdgeData).not.toHaveBeenCalled()
  })
})

describe('instance isolation across rebuilds (dev double-mount safety)', () => {
  it('gives each Graph its own mount node inside the host and removes it on cleanup', () => {
    const { unmount } = render(
      <ThemeProvider>
        <GraphView nodes={NODES} edges={EDGES} defaultKinds={CLASS_ONLY} onSelect={vi.fn()} />
      </ThemeProvider>,
    )
    const g = lastG6()!
    const mount = g.options.container as HTMLElement
    const host = mount.parentElement!
    expect(host.contains(mount)).toBe(true)
    unmount()
    expect(document.body.contains(mount)).toBe(false)
  })

  it('a second build mounts a fresh node, never reusing the first', () => {
    const { rerender } = render(
      <ThemeProvider>
        <GraphView nodes={NODES} edges={EDGES} defaultKinds={CLASS_ONLY} onSelect={vi.fn()} />
      </ThemeProvider>,
    )
    const first = (lastG6()!.options.container as HTMLElement)
    rerender(
      <ThemeProvider>
        <GraphView
          nodes={[...NODES, { id: 'zz', curie: 'ex:ZZ', label: {}, kind: 'class' }]}
          edges={EDGES}
          defaultKinds={CLASS_ONLY}
          onSelect={vi.fn()}
        />
      </ThemeProvider>,
    )
    const second = lastG6()!.options.container as HTMLElement
    expect(second).not.toBe(first)
  })
})
