import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GEdge } from '../api/types'
import { ThemeProvider } from '../theme/ThemeProvider'
import GraphView, { toFlowEdges, type GraphViewNode } from './GraphView'

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

function draw(extra: { showControls?: boolean } = {}) {
  return render(
    <ThemeProvider>
      <GraphView nodes={NODES} edges={EDGES} onSelect={vi.fn()} {...extra} />
    </ThemeProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  cleanup()
})

describe('GraphView', () => {
  it('renders every node with the subclass badge, legend and controls', async () => {
    draw()
    expect(await screen.findByText('ex:A')).toBeTruthy()
    expect(screen.getByText('ex:B')).toBeTruthy()
    expect(screen.getByText('ex:C')).toBeTruthy()
    expect(screen.getByText('ex:hasTopping')).toBeTruthy()
    // Badge = count of subClassOf edges whose target is the node (b and c).
    expect(screen.getByTitle('直接子类数').textContent).toBe('2')
    // ThemeProvider resolves system -> light; the canvas follows via colorMode.
    expect(document.querySelector('.react-flow.light')).toBeTruthy()
    // Legend spells out the three edge semantics.
    expect(screen.getByText('子类（subClassOf）')).toBeTruthy()
    expect(screen.getByText('对象属性')).toBeTruthy()
    expect(screen.getByText('数据属性')).toBeTruthy()
    // Zoom controls default to visible.
    expect(document.querySelector('.react-flow__controls')).toBeTruthy()
  })

  // React Flow only mounts edges once node measurement completes; the no-op
  // ResizeObserver stub in test/setup.ts keeps that from ever happening, so
  // label show/hide is asserted via the switch itself here and via the
  // toFlowEdges mapping below.
  it('toggles the edge-label switch off and back on', async () => {
    draw()
    expect(await screen.findByText('ex:A')).toBeTruthy()
    const btn = screen.getByRole('button', { name: '标签' })
    expect(btn.getAttribute('aria-pressed')).toBe('true')
    await userEvent.click(btn)
    expect(btn.getAttribute('aria-pressed')).toBe('false')
    await userEvent.click(btn)
    expect(btn.getAttribute('aria-pressed')).toBe('true')
  })

  it('classes-only filter drops property nodes and their edges', async () => {
    draw()
    expect(await screen.findByText('ex:hasTopping')).toBeTruthy()
    await userEvent.click(screen.getByRole('radio', { name: '仅类' }))
    expect(screen.getByText('ex:A')).toBeTruthy()
    expect(screen.getByText('ex:B')).toBeTruthy()
    expect(screen.getByText('ex:C')).toBeTruthy()
    expect(screen.queryByText('ex:hasTopping')).toBeNull()
    // The class-property edge is pruned along with its endpoint.
    expect(screen.queryByText('property')).toBeNull()
    await userEvent.click(screen.getByRole('radio', { name: '全部' }))
    expect(screen.getByText('ex:hasTopping')).toBeTruthy()
  })

  it('props-only filter keeps just the property node', async () => {
    draw()
    expect(await screen.findByText('ex:A')).toBeTruthy()
    await userEvent.click(screen.getByRole('radio', { name: '仅属性' }))
    expect(screen.getByText('ex:hasTopping')).toBeTruthy()
    expect(screen.queryByText('ex:A')).toBeNull()
    expect(screen.queryByText('ex:B')).toBeNull()
    expect(screen.queryByText('ex:C')).toBeNull()
  })

  it('hides the zoom controls when showControls is false', async () => {
    draw({ showControls: false })
    expect(await screen.findByText('ex:A')).toBeTruthy()
    expect(document.querySelector('.react-flow__controls')).toBeNull()
  })
})

describe('toFlowEdges', () => {
  // React Flow edge labels measure to zero in jsdom; the mapping itself is
  // covered here, label visibility in DOM above.
  const all = new Set(['a', 'b', 'c', 'd', 'p'])
  const edges: GEdge[] = [
    { source: 'b', target: 'a', kind: 'subClassOf' },
    { source: 'a', target: 'p', kind: 'property' },
    { source: 'd', target: 'a', kind: 'datatype' },
    { source: 'a', target: 'ghost', kind: 'subClassOf' },
  ]

  it('encodes the three edge semantics via CSS tokens', () => {
    const flow = toFlowEdges(edges, all, false)
    expect(flow).toHaveLength(3) // edge to a filtered-out endpoint is dropped
    expect(flow[0].style).toMatchObject({
      stroke: 'var(--color-edge-sub)',
      strokeDasharray: '6 5',
    })
    expect(flow[1].style).toMatchObject({ stroke: 'var(--color-primary)' })
    expect(flow[1].style?.strokeDasharray).toBeUndefined()
    expect(flow[2].style).toMatchObject({
      stroke: 'var(--color-ink-3)',
      strokeDasharray: '1 4',
    })
  })

  it('labels edges only when enabled', () => {
    expect(toFlowEdges(edges, all, true).map((e) => e.label)).toEqual([
      'subClassOf',
      'property',
      'datatype',
    ])
    expect(toFlowEdges(edges, all, false).every((e) => e.label === undefined)).toBe(true)
  })
})
