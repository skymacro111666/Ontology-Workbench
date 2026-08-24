import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GEdge } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
import { lastG6, MockGraph, resetG6 } from '../test/g6Mock'
import GraphView, { computeSubCounts, toG6Edges, toG6Nodes, type GraphViewNode } from './GraphView'

/* G6 renders on canvas, which jsdom cannot provide — the module is mocked and
   assertions target (a) the DOM overlays (legend/controls, real) and (b) the
   data passed into the mocked Graph (constructor data / setData / update*).
   Pure mappings are covered directly below. */

vi.mock('@antv/g6', async () => {
  const { MockGraph } = await import('../test/g6Mock')
  return { Graph: MockGraph }
})

const TOKENS = {
  primary: '#4f46e5',
  primaryFg: '#ffffff',
  panel: '#ffffff',
  line: '#e2e8f0',
  ink: '#0f172a',
  ink3: '#94a3b8',
  edgeSub: '#8b5cf6',
  mono: 'mono',
}

const NODES: GraphViewNode[] = [
  { id: 'a', curie: 'ex:A', label: {}, kind: 'class', highlighted: true },
  { id: 'b', curie: 'ex:B', label: {}, kind: 'class' },
  { id: 'c', curie: 'ex:C', label: {}, kind: 'class' },
  { id: 'p', curie: 'ex:hasTopping', label: {}, kind: 'property' },
]

const EDGES: GEdge[] = [
  { source: 'b', target: 'a', kind: 'subClassOf' },
  { source: 'c', target: 'a', kind: 'subClassOf' },
  { source: 'a', target: 'p', kind: 'property' },
]

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
    edges: { id: string; source: string; target: string; style: Record<string, unknown> }[]
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
  it('passes every node (highlight star, subclass badge) and edge to the canvas', () => {
    draw()
    const { nodes, edges } = lastData()
    expect(nodes.map((n) => n.style.labelText)).toEqual(['ex:A ★', 'ex:B', 'ex:C', 'ex:hasTopping'])
    // Badge = count of subClassOf edges whose target is the node (b and c).
    expect(nodes.find((n) => n.id === 'a')?.style.badges?.[0].text).toBe('2')
    expect(edges).toHaveLength(3)
    // Legend and zoom controls render as DOM overlays.
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
    expect(screen.getByText('对象属性')).toBeTruthy()
    expect(screen.getByText('数据属性')).toBeTruthy()
    expect(screen.getByRole('button', { name: '适配' })).toBeTruthy()
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
    expect(on.map((e) => e.style.labelText)).toEqual(['subClassOf', 'subClassOf', 'property'])
  })

  it('classes-only filter drops property nodes and their edges', async () => {
    draw()
    await userEvent.click(screen.getByRole('radio', { name: '仅类' }))
    const data = lastData('setData')
    expect(data.nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'c'])
    // The class-property edge is pruned along with its endpoint.
    expect(data.edges.every((e) => e.source !== 'a' || e.target !== 'p')).toBe(true)
    await userEvent.click(screen.getByRole('radio', { name: '全部' }))
    expect(lastData('setData').nodes.map((n) => n.id)).toContain('p')
  })

  it('props-only filter keeps just the property node', async () => {
    draw()
    await userEvent.click(screen.getByRole('radio', { name: '仅属性' }))
    const data = lastData('setData')
    expect(data.nodes.map((n) => n.id)).toEqual(['p'])
  })

  it('hides the zoom controls when showControls is false', () => {
    draw({ showControls: false })
    expect(screen.queryByRole('button', { name: '适配' })).toBeNull()
    // The legend stays regardless.
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
  })
})

describe('toG6Edges', () => {
  const all = new Set(['a', 'b', 'c', 'd', 'p'])
  const edges: GEdge[] = [
    { source: 'b', target: 'a', kind: 'subClassOf' },
    { source: 'a', target: 'p', kind: 'property' },
    { source: 'd', target: 'a', kind: 'datatype' },
    { source: 'a', target: 'ghost', kind: 'subClassOf' },
  ]

  it('encodes the three edge semantics via tokens with matching arrows', () => {
    const mapped = toG6Edges(edges, all, false, TOKENS)
    const st = (e: { style?: Record<string, unknown> }) => e.style ?? {}
    expect(mapped).toHaveLength(3) // edge to a filtered-out endpoint is dropped
    expect(st(mapped[0])).toMatchObject({ stroke: '#8b5cf6', lineDash: [6, 5], endArrow: true })
    expect(st(mapped[1])).toMatchObject({ stroke: '#4f46e5', endArrowFill: '#4f46e5' })
    expect(st(mapped[1]).lineDash).toBeUndefined()
    expect(st(mapped[2])).toMatchObject({ stroke: '#94a3b8', lineDash: [1, 4] })
  })

  it('labels edges only when enabled', () => {
    const st = (e: { style?: Record<string, unknown> }) => e.style ?? {}
    expect(toG6Edges(edges, all, true, TOKENS).map((e) => st(e).labelText)).toEqual([
      'subClassOf',
      'property',
      'datatype',
    ])
    expect(toG6Edges(edges, all, false, TOKENS).every((e) => st(e).labelText === '')).toBe(true)
  })
})

describe('toG6Nodes', () => {
  it('styles the highlighted entity and property nodes apart from classes', () => {
    const mapped = toG6Nodes(NODES, computeSubCounts(EDGES), TOKENS)
    const by = (id: string) => mapped.find((n) => n.id === id) as G6Datum
    // Highlighted: 2px primary border, star, bold label.
    expect(by('a').style).toMatchObject({ stroke: '#4f46e5', lineWidth: 2, labelFontWeight: 700 })
    expect(by('a').style.labelText).toBe('ex:A ★')
    // Property node: dashed violet border.
    expect(by('p').style).toMatchObject({ stroke: '#8b5cf6', lineDash: [4, 3] })
    // Plain class: solid grey border, no dash.
    expect(by('b').style).toMatchObject({ stroke: '#e2e8f0' })
    expect(by('b').style.lineDash).toBeUndefined()
    expect(by('b').style.badges).toBeUndefined()
  })
})
